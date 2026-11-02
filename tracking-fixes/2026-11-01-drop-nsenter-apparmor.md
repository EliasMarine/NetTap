# 2026-11-01 — Drop nsenter: Ubuntu AppArmor blocked every daemon host command

**Status:** Fixed in code; device check pending.
**Linear:** NET-126.
**Branch:** `fix/daemon-drop-nsenter`, off `chore/mirror-mode-verify`.
**Chain:** DEPLOYMENT-ISSUES.md Chain 22.

## What changed
- **Direct commands:** `_run_nsenter` in `mirror_manager.py`, `bridge_manager.py`, `bridge_health.py` and `dhcp_gateway_host.py` now runs the command directly. Before, it ran `nsenter -t 1 -n -- <cmd>`. The method name is kept, so the tests that patch it stay valid.
- **NIC discovery:** `nic_discovery._get_ipv4_map` no longer tries nsenter first.
- **Fail-closed guard:** `api/setup._nic_in_use_problem` now refuses a NIC when `ip -j link show dev X` returns nothing. Before, a failed `ip` call looked like "spare".
- **CR-076 startup guard:** `main._build_capture_manager` skips `MirrorManager.setup()` when the NIC carries the default route or has an IPv4 address. It logs `Mirror setup skipped, nothing changed`.
- **Review follow-ups (same day):**
  - The boot unit no longer runs `ip addr flush` by NIC name at every boot (that was CR-076 too).
  - Its `ethtool -K` line is now non-fatal.
  - Go Live's `POST /api/setup/bridge` gets the bridge preview's in-use check and name validation.
  - The deploy script now counts AppArmor refusals only from after the recreate, reads the kernel log with sudo, and stops if the pull fails.
- **Verify script:** `verify-mirror-mode.sh` reports an admin-DOWN port as such, instead of "check the cable". It also prints the systemd unit state once (it used to print `not-found` and `missing` on two lines).
- **Deploy script:** new `scripts/remote/deploy-drop-nsenter.sh`.
- **Comments only:** compose and Dockerfile comments now say `network_mode: host` is load-bearing, and that SYS_PTRACE and pid: host were only for nsenter.

## Root cause
On Ubuntu 24.04 (the G11), the kernel logged this every 30 s:
`apparmor="DENIED" operation="ptrace" profile="docker-default" comm="nsenter" requested_mask="read" peer="unconfined"`

- docker-default only allows ptrace between docker-default peers, and host PID 1 is unconfined.
- So every host command failed, and `MirrorManager.setup()` stopped at its first check.
- The capture port therefore stayed admin DOWN, and no netplan file or boot unit was written.
- The daemon already shares the host network namespace (`network_mode: host`), so nsenter was unnecessary.

## Steps / solution
1. Map every nsenter caller. All of them used the network-only form, `-t 1 -n`.
2. Run the commands directly.
3. Make the in-use guard fail closed.
4. Add the CR-076 guard. The flush becomes real once nsenter stops failing.
5. On the device, rebuild and recreate only the daemon, then start the boot unit it writes. The unit applies `disable_ipv6`, which the daemon can't do because `/proc/sys` is read-only in the container.

## Files touched
- `daemon/services/{mirror_manager,bridge_manager,bridge_health,dhcp_gateway_host,dhcp_gateway}.py`
- `daemon/api/{nic_discovery,setup,bridge}.py`
- `daemon/main.py`
- `daemon/tests/test_host_commands.py` (new), `test_main.py`, `test_setup_configure.py`, `test_mirror_manager.py`, `test_bridge_api.py`
- `docker/docker-compose.yml`, `docker/Dockerfile.daemon` (comments only)
- `scripts/remote/verify-mirror-mode.sh`, `scripts/remote/deploy-drop-nsenter.sh` (new)
- `Debugging/DEPLOYMENT-ISSUES.md`, `Debugging/BRIDGE-ARCHITECTURE.md`, `Debugging/RELEASE-VERIFICATION.md`

## Test results
- pytest: 2352 passed, up from 2345. The first 4 new tests:
  - all four helpers run commands without nsenter;
  - a missing binary is named in the error;
  - the guard fails closed;
  - CR-076 skips setup.
- Review follow-ups added 3 more tests:
  - the boot unit has no flush and has a non-fatal `ethtool -K`;
  - bridge create refuses an in-use NIC;
  - bridge create refuses a bad NIC name.
- `ruff check` and `ruff format --check` are clean.
- `shellcheck -S warning` is clean on both scripts.
- The admin-UP regex was self-checked against five flag strings.
- Device run: pending. Command: `bash /home/nettap/NetTap/scripts/remote/deploy-drop-nsenter.sh`.

## Lessons
- Read `journalctl -k | grep DENIED` before assuming a capability is missing. The `adm` group can read it without sudo.
- A helper that returns `[]` on failure turns every check built on it into "looks fine".
- Fixing one failure can arm a dormant hazard: CR-076 only became reachable once nsenter worked.

## Next steps
- Run the deploy script on the G11. Then reboot and run `verify-mirror-mode.sh` again.
- After that run, decide whether to drop SYS_PTRACE and pid: host from the daemon.
- Optional follow-up refactor: rename `_run_nsenter` to `_run_host`.
- Still open:
  - the daemon can't turn IPv6 off at runtime after a wizard change;
  - the installer prints the bridge rewire banner even with `--skip-bridge`;
  - its OpenSearch check doesn't log in;
  - preflight picked the Wi-Fi card as the LAN port.
