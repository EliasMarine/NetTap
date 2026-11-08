# Installer: logo, step progress, download spinner and summary cards (NET-204)

**Date:** 2026-11-07
**Branch:** `feature/install-experience`
**Linear:** NET-204
**Status:** In review.

## Problem

`sudo scripts/install/install.sh` printed a wall of `[NetTap] <timestamp>` lines. Steps were numbered 0/8 to 8/8. Each Malcolm image pull streamed docker's own output, so a 10 to 20 minute download looked like nothing was happening. A failure ended on the last error line, with no word on which step stopped or how to try again. The end of a good install was a `====` box that was easy to scroll past.

## Fix

- **`scripts/common.sh`**
  - `NETTAP_UI` (`plain` by default, `fancy` when the installer sets it). In `fancy`, `log`, `warn`, `error` and `debug` drop the prefix and timestamp and indent under the step header. `error` still exits 1.
  - New `status_line OK|WARN|FAIL|SKIP "message"`. Plain prints today's `[ OK ]` / `[WARN]` / `[FAIL]` / `[SKIP]`; fancy prints ✓ / ! / ✗ / -. It always returns 0.
  - On the Linux text console (`TERM=linux`) ✓ and ✗ become `+` and `x`.
- **`scripts/install/ui.sh`** (new)
  - Picks the layout once (`ui_enable`) and exports it to child scripts.
  - The logo: 73 columns, or a 3-row compact one below 80 columns.
  - The "Before we start" card: WAN and LAN ports with cable state, the dashboard address, what happens to the bridge, and "usually 10 to 20 minutes, mostly downloading".
  - A 5-second countdown ("Enter starts now, Ctrl-C cancels") on interactive runs without `--non-interactive`.
  - `ui_step`: `[N/9]` with a progress bar.
  - `ui_spin`: a spinner around a command. It keeps the command's output in a file and puts back the caller's traps.
  - The summary cards (installed, and deferred bridge), with the cabling steps and a one-line diagram.
  - The failure card ("Install stopped at step N/9: <title>", a hint for that step, the same command to run again, "add -v for debug output") and "Install cancelled at step N/9" on Ctrl-C.
- **`scripts/install/install.sh`**
  - Steps are 1/9 to 9/9 (were 0/8 to 8/8). Each step starts with `ui_step`.
  - The card shows after `.env` is loaded, so it has the port names from NIC discovery.
  - An `EXIT` trap prints the failure card or the cancel line and keeps the real exit status.
  - Sourcing the script no longer parses arguments; `install_entry` does that.
  - The verification checks use `status_line`.
  - The old header and summary boxes are kept as OLD CODE.
- **`scripts/install/deploy-malcolm.sh`**
  - Under the installer on a terminal, each image pull is one spinner line.
  - A failed pull prints the last 10 lines, keeps its output file and prints its path. A good pull deletes its file.
  - Run on its own, the script keeps its header box.
- **`scripts/install/validate-hardware.sh`**
  - The checks use `status_line`.
  - No header box under the installer. Run on its own, it keeps it.
- **`tests/scripts/test_install_ui.bats`** (new): 31 tests.

## Plain vs interactive output

- **Interactive** (`NETTAP_UI=fancy`): stdout is a terminal and `TERM` is not `dumb`, or `NETTAP_COLOR=always`. Colour, the progress bar, the spinner and the glyphs.
- **Plain**: output is piped or logged, or `NETTAP_COLOR=never`. Today's `[NetTap] <timestamp>` and `[ OK ]` lines, with the new step numbers (`[Step 1/9]`). The logo and the cards still print, with no colour.
- The plain container run had zero escape codes.

## Plan review

- **`/codex-review`:** approved in round 3. Every finding was accepted.
  - Round 1, six findings:
    - a background pull ignored Ctrl-C;
    - the card showed before `.env` was loaded;
    - strict-mode traps in the countdown and the probes;
    - sourcing `install.sh` ran its argument parsing;
    - the pull log's lifecycle;
    - how `status_line` maps an outcome.
  - Round 2, three findings:
    - the cancel handler under `set -e`;
    - restoring the traps when there was no trap before;
    - tests for a bare call and for SIGINT to the whole process group.

## Tests

- 31 new bats tests in `tests/scripts/test_install_ui.bats`. All 31 pass on macOS bash 3.2, and on Ubuntu 24.04 bash 5.2 in three runs in a row.
- Full bats suite: 245/245 on macOS bash 3.2.
- In an Ubuntu 24.04 container the suite has the same 32 environment failures on `main` and on this branch. None are new.
- Daemon pytest: 3,959 passed.
- `shellcheck -x` at warning level is clean on all install scripts.

## Container smoke

Three runs in an x86-64 Ubuntu 24.04 container, on a copy of the repo:

1. **Real `install.sh --dry-run --non-interactive`.** It stops at step 1 because the container has no physical NICs. It shows the failure card ("Install stopped at step 1/9: Pre-flight checks") and exits 1.
2. **Real steps 2 to 9, with only the hardware check swapped out.** It runs through to the summary card. The same run with `NETTAP_COLOR=never` has zero escape codes.
3. **Real `deploy-malcolm.sh --pull-only` with a stand-in docker.** The spinner shows for all 12 images, and no temp files are left.

## Not done

- **No device deploy.** The installer is not part of the running stack on the G11, and even `--dry-run` writes `nettap.service`.
- `preflight.sh`'s NIC prompts are unchanged.
- docker compose output inside the Malcolm step is unchanged.

## Lessons

- **bash 3.2 prints a stray `\177` for an empty `"$*"` inside `${*:+...}`.** Test for an empty `$*` first.
- **A non-interactive shell starts background jobs with SIGINT ignored.** A spinner must kill its child itself on Ctrl-C.
- **In bats on bash < 4.1, a `[[ ]]` or `! cmd` in the middle of a test never fails it.** End `[[ ]]` with `|| false` and use `run` for negative checks.
- **`pgrep -f "text"` matches any process whose command line holds the text, including the script that runs pgrep.** Write one character as a class (`32[.]3`).
- **Colour codes between characters break substring checks in tests.** Strip them, or test the plain layout.

## Pre-commit reviews

- `/deep-review`: no findings (`security-reviews/feature-install-experience/security-review.md`).
- `/ponytail-review`: two findings, both fixed. (1) When `mktemp` fails, `UI_SPIN_LOG` is empty, and the pull's success branch ran `rm -f ""` as root under `set -e`. It now removes the file only when the path is set, and two tests cover a missing `TMPDIR`. (2) Two copies of the duration formatter became one, `_ui_duration`.

## Two-angle review

- **security-engineer:** nothing at MEDIUM or above. One LOW, fixed: `installer_version` ran `git describe` as root with a `safe.directory` override. It now runs git as the checkout's owner (`runuser -u <owner>`), with no override.
- **Code reviewer:** one Medium and some Lows, all fixed.
  - Medium: with stdout closed (ssh dropped), a failing `printf` in an exit handler could replace the exit status under `set -e`. Both handlers now run `set +e` first. A test closes stdout and checks the status survives.
  - `! pgrep` in the middle of a test never fails it under `set -e`; the tests now use `run pgrep` and check the status.
  - On bash 3.2, a `[[ ]]` in the middle of a test does not fail it. Every one now ends in `|| false`. That exposed one test that only passed by accident (macOS `wc -l` pads the count), now fixed.
  - Plain mode printed "Review the ✗ lines above"; it now says `[FAIL]`.
  - The two signal tests waited a fixed time. They now poll until the spinner's child is running. The poll pattern is `sleep 32[.]3`, so it cannot match the launcher's own command line.
  - A new test checks every failure hint names a real step title.
- **Accepted, not changed:** in plain mode the skip lines ("Skipped (--skip-bridge)") read differently, and step 8 now prints "UFW not active, nothing to change".
- **Follow-up:** `scripts/bridge/setup-bridge.sh` and `harden-bridge.sh` still echo 26 raw `[ OK ]` lines, which are not indented under the step header. The bridge path is high-stakes, so they are left for their own change.
