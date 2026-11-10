# Fresh-install cloud test (H2 + H7), 2026-11-10

**Linear:** NET-245 (this test), NET-246 (the installer bug it found), NET-244 (`--non-interactive` on two ports)
**Branch:** `chore/fresh-install-cloud-test` (the fix is on its own branch, `fix/install-curlrc-fresh-env`)
**Status:** H2 and H7 pass on cloud mirror mode, Ubuntu 24.04 and 22.04, with the NET-246 fix (`a5638f08`)

## Why
Release-gate rows H2 (install from scratch) and H7 (setup wizard, settings persist) had never been run. They are the first thing every tester does. The dev Mac is arm64 and Malcolm 26.10.0 is amd64-only, so the test runs on throwaway DigitalOcean droplets (16 GB, 4 vCPU, $0.125/h each).

## What was built
`scripts/fresh-install-cloud.sh`. It runs on the dev Mac.

Subcommands:
- `up`
- `install`
- `watch` (read-only tmux view of the installer)
- `tunnel`
- `snapshot`
- `after-wizard`
- `ssh`
- `down`
- `status`

It runs the README install exactly: the interactive `sudo scripts/install/install.sh --skip-bridge`, in tmux, with the prompts answered. Safety:
- each run's manifest records the IDs it created;
- the script checks the account first, and deletes only those IDs;
- it deletes a firewall only after its droplet is gone;
- SSH is open only from the caller's IP.

Tests: `tests/scripts/test_fresh_install_cloud.bats`, 11 tests with doctl stubbed.

Plan gate: `/codex-review` approved it in 3 rounds. Codex found that `--non-interactive` aborts on two ports, plus the tunnel CSRF origin, ownership, the exit code, and settings checks.

## Results

| Run | Commit | Install | Wizard | Reboot + persistence + login |
|---|---|---|---|---|
| 24.04 `20261110t010038z` | `fe10a592` (main) | **FAIL**: exit 2 at step 5/9 after 2 min (NET-246) | — | — |
| 22.04 `20261110t010041z` | `fe10a592` (main) | **FAIL**: same | — | — |
| 24.04 `20261110t014421z` | `a5638f08` (fix) | **PASS**: 10 min, 5/5 checks | **PASS**: 7 steps, Mirror on eth1, `capture_restart.errors` empty | **PASS**: 10/10, twice (two reboots) |
| 22.04 `20261110t014424z` | `a5638f08` (fix) | **PASS**: 8 min 55 s, 5/5 checks | **PASS**: same | **PASS**: 10/10, twice |

The wizard choices were all non-defaults, so a persistence pass proves they were saved:
- Mirror / SPAN;
- capture eth1, management eth0;
- retention 21 / 45 / 14 days;
- thresholds 75 % / 92 %;
- enrichment left at passive (no UniFi).

The after-wizard check compares 20 effective values with those choices before and after a reboot: capture-mode.conf, the daemon .env, retention.json, and eth1's state (UP, PROMISC, no address).

The first after-wizard run on each box failed only the second-admin check. That was a harness bug: it expected an HTTP redirect, and SvelteKit sends JSON. Each box had 1 account. The fixed check passed on both.

Evidence for each run is in the worktree's gitignored `.fresh-install/<run>/`:
- `install.log` (the full TTY transcript);
- `install-run.txt`;
- `docker-ps-a.txt`;
- `settings-before.txt` and `settings-after.txt`;
- `after-wizard*.txt`;
- `wizard-verification.jpg`.

## Found
1. **NET-246 (Urgent): every fresh install since #77 (2026-11-02) stopped at step 5.**
   - `_lock_curlrc` grepped a `docker/.env` that doesn't exist yet, so `set -euo pipefail` ended the installer, and re-running failed the same way.
   - The installer's hint ("check you can reach ghcr.io") pointed at the wrong thing.
   - It was hidden on the G11 because the G11 was installed before #77, and in bats because the suite turns pipefail off.
   - Fixed on `fix/install-curlrc-fresh-env`, with two strict-mode tests that fail on the old code.
2. **NET-244: `install.sh --skip-bridge --non-interactive` aborts on a two-port box.** The internet port is taken for MGMT, which leaves no LAN port. Not fixed here.
3. **UX: the final install card prints bridge cabling under `--skip-bridge`.** It tells the user to "Keep eth2 (MGMT) connected", and the box has no eth2. Preflight also warns "no dedicated management NIC… need Wi-Fi or a VLAN", which isn't true in mirror mode. Both are noted on NET-246 as follow-ups.
4. **The wizard's Interfaces step offers eth0 (the management port, which has the IP) as a capture choice.** Not tried; the in-use guard should refuse it. Worth a follow-up check.

## Harness lessons (fixed in the script)
- DO's DNS resolver is only reachable over the VPC NIC. Taking eth1's address away broke DNS, so DNS moves to DO's public resolvers on eth0.
- The 22.04 image can take more than 5 min to first SSH, so the wait is 10 min.
- A filtering network extension on the dev Mac (AdGuard) dropped direct SSH to the droplets. `FI_JUMP=<host>` goes through another machine. The script also shares one SSH connection per droplet.
- DO's list endpoints lag a few seconds behind a delete, so the teardown check polls for up to 2 min.
- macOS lets a normal user bind port 443 only on 0.0.0.0. `FI_TUNNEL_BIND=0.0.0.0` opens the setup page to the LAN for the wizard's minutes, still behind the setup code.
- The tunnel must not share the SSH connection: the master process can't bind the port.
- SvelteKit answers a non-browser form POST with JSON (`{"type":"redirect",…}`), not an HTTP redirect. The second-admin check reads that and also counts accounts, which stayed at 1 on both boxes.
- The script must run on bash 3.2 (macOS): no `mapfile`.

## G11 reboot recovery (same day)
The owner rebooted the G11 on `main` `fe10a592`:
- SSH answered after about 140 s;
- all 15 containers were up and healthy about 130 s later;
- the smoke test passed 29/29, with the OpenSearch cluster green through the service curlrc;
- traffic 23:00–00:00 UTC: API 1,530,753,104 B = Zeek final records.

## Not covered
- Real NICs (virtio here) and real mirror traffic: eth1 sees almost nothing, so data accuracy isn't tested. The audit covers that on the G11.
- Inline bridge and DHCP gateway modes.
- A container *recreate*.

## Next
- Merge `fix/install-curlrc-fresh-env` (NET-246) first, then this branch (NET-245).
- Rerun the cloud test against `main` after the merge, before inviting testers.
