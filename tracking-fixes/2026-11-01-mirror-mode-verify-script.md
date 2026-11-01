# 2026-11-01 — verify-mirror-mode.sh (GMKtec G11 mirror trial)

**Status:** Written, shellcheck clean (CI severity: warning). Not run on hardware yet.
**Branch:** `chore/mirror-mode-verify` (off `fix/code-review-batch-1`, PR #147)

## What changed
- New `scripts/remote/verify-mirror-mode.sh`: read-only check of a mirror/SPAN install. It pulls the checked-out branch, waits for daemon and web health, then checks:
  - the daemon reports mirror mode (`/api/capture/mode`)
  - capture-mode.conf and capture.env
  - the capture NIC has no IP, is promiscuous, has offloads off, and reports its ring size
  - the RX counter climbs and enough unicast frames arrive to prove a real mirror
  - drop counters
  - boot persistence: the netplan file, the units, and no other netplan file claiming the NIC
  - the default route is on the management NIC
  - the PCAP_IFACE of every capture container

## Why
The owner is trialing mirror mode on a GMKtec G11 (dual Realtek RTL8125BG). The mirror source is the USW Pro XG 8 PoE uplink to the UDM Pro. No script checked a mirror install end to end, and CLAUDE.md requires multi-step device checks to live in `scripts/remote/`.

## Root cause it guards against
- Netplan applies files in name order and later files win. If the Ubuntu installer configured the capture NIC in `50-cloud-init.yaml`, that file overrides `10-nettap-mirror-<nic>.yaml` written by `MirrorManager`.
- A port that is not mirrored still shows a climbing RX counter (broadcast/multicast). Only a steady stream of other hosts' unicast frames proves the mirror.

## Files
- `scripts/remote/verify-mirror-mode.sh` (new)

## Test results
- `bash -n`: OK. `shellcheck -S warning`: clean.
- The awk parsers were checked against sample `ethtool -g` / `ip -s link` output.
- Device run: pending (`bash scripts/remote/verify-mirror-mode.sh`).

## Lessons
- On a two-NIC box, `install.sh` must run with `--skip-bridge`. Otherwise `preflight.sh` assigns both NICs to WAN/LAN and `setup-bridge.sh` enslaves the management NIC.

## Next steps
- Run it on the G11 after the wizard and switch config, then again after a reboot.
- CR-076 (unguarded flush at `mirror_manager.py:115` on daemon start) is still open.
