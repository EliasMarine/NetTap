# Fresh-install cloud re-test before the LinkedIn post, 2026-11-16

**Linear:** NET-297 (the 22.04 dialog it found), NET-295 (`.claude/` untracked, same session)
**Branch:** `fix/installer-needrestart-prompt` (PR #303)
**Status:** Install passes on Ubuntu 24.04 (tag and `main`) and 22.04 (with the NET-297 fix, no dialog)

## Why
The owner is about to post NetTap on LinkedIn and wanted proof that someone who follows the install instructions gets a working box. The test also had to capture the start of the installer, with the ASCII logo.

Two install paths are live:
- **README:** `git checkout v0.4.0-alpha.1`, then `sudo scripts/install/install.sh --skip-bridge`.
- **nettap.dev:** clones `main` and runs `sudo scripts/install/install.sh` with no tag and no `--skip-bridge`.

## How
`scripts/fresh-install-cloud.sh` (from `main`), on `s-4vcpu-16gb-amd` droplets in lon1. It runs the interactive install in tmux and answers the documented prompts. Bridge mode can't run on a cloud VM (it would bridge the droplet's only uplink), so every run uses `--skip-bridge`.

The Mac can't reach the droplets' port 22 directly (local filtering, as on 2026-11-10), so every run used `FI_JUMP=nettap` (ProxyJump through the G11, same public IP).

## Results

| Run | Commit | Ubuntu | Install | Notes |
|---|---|---|---|---|
| `20261116t022059z-u2404` | `616877fe` (tag `v0.4.0-alpha.1`) | 24.04.5 | **PASS**: 9 min, 5/5 checks | The README path |
| `20261116t022104z-u2404` | `4cc3cc73` (`main`) | 24.04.5 | **PASS**: 9 min, 5/5 checks | The nettap.dev clone (with `--skip-bridge`) |
| `20261116t022101z-u2204` | `4cc3cc73` (`main`) | 22.04.5 | **PASS after 2 dialogs answered by hand**: 21 min, 5/5 checks | needrestart's "Daemons using outdated libraries" checklist, once in the dependency install and once in `docker-compose-v2` (NET-297) |
| `20261116t025147z-u2204` | `e9872d58` (fix) | 22.04.5 | **PASS**: 9 min, 5/5 checks | A watcher polled for any `whiptail` process every 2 s for the whole install and saw none |

The five checks: `install.sh --skip-bridge` exits 0; every default service is present and the non-capture ones are healthy; daemon `/api/health` 200; unauthenticated `https://localhost/` ends at `/setup`; the setup code the installer prints matches the documented command.

The wizard (H7) wasn't repeated. It passed on 2026-11-10, and nothing since has changed the wizard's save path.

## The 22.04 dialog (NET-297)
- **Symptom:** a full-screen whiptail checklist stops step 2 twice. A person at the keyboard presses Enter and goes on. An unattended install waits forever.
- **Root cause:** Ubuntu 22.04's needrestart asks which services to restart after an `apt-get install` that upgraded a library they use. 24.04 restarts them on its own. The 2026-11-10 22.04 run didn't hit it, probably because that day's image was closer to the archive.
- **Fix:** `export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a` at the top of `install.sh`, and in `setup-watchdog.sh` and `setup-firewall.sh`. Those two are standalone scripts that `install.sh` never runs, which the pre-merge review spotted.
- **Tests:** two bats tests in `tests/scripts/test_install.bats`. The first fails without the export. bats 406 pass, shellcheck clean.
- **Reviews:** `/deep-review` found nothing. In the two-angle review, the security angle found nothing and the shell angle found the standalone-scripts gap, now fixed.

## Screenshot
The start of the `v0.4.0-alpha.1` install, captured from the tmux scrollback with its colours (`tmux capture-pane -e -S -`), then drawn with xterm.js's WebGL renderer so the block logo joins up as it does in a real terminal. The full yellow-and-cyan "NetTap" logo, the bolt and the version line are there. The image stays on the owner's Mac; it isn't in the repo.

## Findings for the owner (not fixed here)
- **The v0.4.0-alpha.1 tag still has the 22.04 dialog.** README users on 22.04 will see it until a new tag (for example `v0.4.0-alpha.2`) is cut from `main` after #303.
- **nettap.dev disagrees with the README.** It says "No version has been tagged yet", and its install block has no `git checkout v0.4.0-alpha.1` and no `--skip-bridge`, so it runs inline-bridge mode, which the README calls partly tested.
- **The NIC discovery text talks about a bridge under `--skip-bridge`.** It still prints "Your current internet NIC (eth0) is assigned to the bridge. Internet will be unavailable until cables are rewired…", which is confusing in mirror mode.
- **Droplet boot time varies.** One droplet never opened port 22 in 8 minutes and was destroyed. Another took about 10 minutes, just past the script's 600 s SSH wait, then worked.

## Cleanup
All test droplets were destroyed through `fresh-install-cloud.sh down`. `status` shows all five runs destroyed, and no `nettap-fi-*` droplet, firewall, key or tag is left. The account's other droplets weren't touched.
