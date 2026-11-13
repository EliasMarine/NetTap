# Installer, Go Live and capture-start fixes, plus an uninstall script

**Date:** 2026-11-12
**Branch:** `fix/installer-two-port-and-setup-guide-bugs`
**Linear:** NET-244, NET-211
**Status:** Pushed, PR not opened (the lead opens it). Not verified on a device. Plan approved by Codex in 3 rounds: `.codex-review/2026-11-12-175020-installer-go-live/PLAN.md` (not committed).

## What was wrong

NET-244: `install.sh --skip-bridge --non-interactive` aborted on a two-port box. NET-211: eleven bugs found while writing the setup guide. Debugging entry: Chain 33 in `Debugging/DEPLOYMENT-ISSUES.md`.

| # | Problem | Root cause |
|---|---|---|
| NET-244 | Two-port non-interactive `--skip-bridge` install stopped at "Could not assign WAN and LAN NICs" | `step_nic_preflight` ran preflight's NIC role assignment even though the wizard picks the ports |
| 1 | A hand-copied `.env` gave the box `192.168.1.100` on `eth2` | `.env.example` had active `MGMT_*`/`WAN_*`/`LAN_*` values |
| 2 | Go Live offered "Create bridge" in mirror mode | `bridgeFlow` only excluded DHCP gateway mode |
| 3 | Go Live offered eth0/eth1, or the ports another browser saved | Ports came from localStorage with a hard-coded fallback |
| 4 | The wizard's self-traffic field took typed input it never saved | Editable `bind:value` on a detected-only value |
| 5 | The installer's OpenSearch check always said "not responding yet" | Unauthenticated curl to a secured cluster |
| 6 | Summary and firewall pointed at Malcolm on :9443 | Nothing publishes 9443; Dashboards is `/dashboards/` behind NetTap's nginx |
| 7 | The installer enabled UFW where the owner had it off | `grep -q active` also matches "inactive" |
| 8 | `--dry-run` wrote system files, installed packages and ran deploy-malcolm.sh | Plain `cat >` / direct calls instead of `run` |
| 9 | Zeek and Suricata FATAL before the wizard, and in bridge mode after Go Live | They start on `PCAP_IFACE=br0` before br0 exists; supervisord gives up after 3 tries |
| 10 | Header names `--persist-bridge` | parse_args only knows `--no-persist-bridge` |
| 11 | No uninstall | Never written |

## What changed

- `scripts/install/install.sh`: NET-244 skip; `opensearch_health` (#5); firewall step drops 9443 (#6); `^Status: active` (#7); dry run through `run`/`write_file`, daemon.json moved into `configure_docker_daemon` (#8); header (#10); daemon.json records `.nettap-installed`/`.nettap-backup`, old records dropped first (#11).
- `scripts/common.sh`: `write_file` (#8).
- `scripts/bridge/setup-bridge.sh`: dry run writes nothing and loads no module (#8).
- `scripts/install/ui.sh`, `scripts/install/setup-firewall.sh`: no 9443 (#6).
- `.env.example`: port names and management address commented out (#1).
- `config/capture/nettap-capture-env.sh`: waits for every `PCAP_IFACE` interface (#9).
- `daemon/services/capture_config.py` `saved_bridge_ports()`, `daemon/api/capture.py`: `/api/capture/mode` returns the saved bridge ports in bridge mode (#3).
- `web/src/routes/go-live/+page.svelte`, `web/src/lib/api/capture.ts`: mirror card, ports from the daemon, notice without saved ports (#2, #3). `web/src/routes/setup/+page.svelte`: localStorage writes commented out (#3), read-only self-traffic field (#4).
- `scripts/install/uninstall.sh` (new, #11), README line.
- `scripts/remote/deploy-installer-go-live.sh` (new).
- Replaced code kept as `OLD CODE` everywhere.

## Test results

- `bats tests/scripts`: 347/347 pass. New: test_install.bats (NET-244, #5–#8, #10, daemon.json records), test_preflight.bats (#1, two-port bridge abort pinned), test_setup_bridge_dry_run.bats (#8), test_capture_env_loader.bats (#9, 6 new; every test now passes a fake sysfs), test_uninstall.bats (#11, 16), test_install_ui.bats and test_setup_firewall.bats (#6). Each new test was run against the code before its fix and fails there.
- `shellcheck -S warning` on every script under `scripts/`: clean.
- `cd daemon && python -m pytest`: 4674 passed, 2 failed, 4 skipped. The 2 failures are `test_cert_monitor.py` (date-dependent, fixed on main in 5c1a2962), same as before the branch. 13 new tests in `test_capture_mode_ports.py`. ruff check and format clean.
- `cd web && npx vitest run`: 354 files, 4552 tests pass (4 new). `npx svelte-check`: 0 errors, 2 warnings (both existing). `npm run check:colors`: clean.
- uninstall.sh `--dry-run` fed to the G11 over stdin (writes nothing): lists `nettap.service`, `nettap-mirror.service`, `10-nettap-mirror-enp4s0.yaml`, `99-nettap.conf`, and leaves the Nov 1 `daemon.json` alone with a note (no record).

## Lessons

- bats runs under `/bin/bash` 3.2 on a Mac: a failing `[[ ]]` that isn't a test's last command doesn't fail the test, and an empty array is "unbound" under `set -u`. End mid-test `[[ ]]` checks with `|| false`; expand arrays as `${a[@]+"${a[@]}"}` in scripts tests run.
- A single-file bind mount keeps the old inode after `git pull`; `docker restart` doesn't pick up the new file, recreate the container.
- Stopping `nettap-bypass.service` runs `bypass-mode.sh --disable`, which starts capture; anything that stops NetTap must stop units before `compose down`.

## Review fixes (PR #254)

- The summary card under `--skip-bridge` no longer shows bridge cabling (eth0/eth1 when no ports were set) or "Keep Wi-Fi connected"; it says "open the dashboard; the setup wizard picks the ports". This covers the first NET-246 item (the cabling card).
- uninstall.sh: DHCP gateway mode goes first, its netplan just before its unit, while the daemon still runs, so a run cut short can be run again (before, the netplan outlived the daemon and every re-run refused). `compose down` adds `--profile arkime --profile grafana --remove-orphans`. A `daemon.json` with no record is called an older NetTap's only when it holds NetTap's DNS servers.
- install.sh: the NET-244 path locks `.env` to 600 (preflight.sh, which it skips, did that). The dry run shows `sysctl --system` (the redirect hid it) and, without jq, says what it would add instead of "can't read as JSON".
- The capture env loader repeats its waiting line every 5 minutes.
- Go Live's wiring step shows the "ports aren't saved" notice instead of empty port tags when br0 exists without saved ports.

## Next steps

- Deploy on the G11: `bash scripts/remote/deploy-installer-go-live.sh`.
- Fresh-install checks the G11 can't show: two-port `--skip-bridge --non-interactive`, `install.sh --dry-run` on a clean box, a bridge-mode wizard then Go Live (capture starts when br0 appears), uninstall on a bridge box.
- `deploy-malcolm.sh:234` printed the same 9443 address: fixed by malcolm-bootstrap on `fix/malcolm-bootstrap-and-decimal-sizes` (587e3c8d).
- Out of scope: existing `.env` files keep the old `MGMT_*` values; standalone `deploy-malcolm.sh`/`malcolm-config.sh --dry-run` still write repo config.
