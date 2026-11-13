# The installer keeps the admin password off the command line, 2026-11-13

**Linear:** NET-251
**Branch:** `fix/htpasswd-password-argv`
**Status:** built and tested locally. No device change: the function runs only at install time, and the G11 already has its file.
**Plan:** Codex review, 3 rounds, APPROVED. The plan is in `.codex-review/2026-11-13-093259-htpasswd-argv/` (gitignored).

## Why

`generate_auth` in `scripts/install/malcolm-config.sh` writes `docker/auth/htpasswd` on a fresh install. It had the same problem NET-217 fixed in deploy-malcolm.sh: the password was on a command line.
- **htpasswd path.** `run htpasswd -bcB <file> <user> "$password"`. `-b` takes the password as an argument, so any local account could read it with `ps` while htpasswd ran. `run` also prints its arguments: `[DRY-RUN] $*` in a dry run and `exec: $*` in verbose mode. `install.sh -v` passes `-v` down, so a verbose install printed the password.
- **python3 fallback.** The password was pasted into the `python3 -c` code as `b'${password}'`. It was in python3's arguments, and a `'` in it was a syntax error that stopped the install. A `\` changed the hash, and any non-ASCII character was a syntax error.
- **The fallback is the usual path.** Nothing installs apache2-utils, so a stock Ubuntu box has no htpasswd. The G11 has none, and its `docker/auth/htpasswd` holds the python `{SSHA}` form.

The generated password is letters and digits, so only a password set in `NETTAP_ADMIN_PASSWORD` could break the code. Every password was visible in `ps`.

## What changed

`scripts/install/malcolm-config.sh`, `generate_auth` only (old lines kept as OLD CODE):
- **htpasswd:** `run htpasswd -icB <file> <user> < <(printf '%s\r\n' "$password")`.
  - `-i` reads the password from stdin. `printf` is a bash builtin, so the password is in no process's arguments, and `run`'s log line is now `htpasswd -icB <file> <user>`.
  - Why the `\r\n`: htpasswd reads all of stdin, then strips one final LF and the CR before it. With a here-string, a password ending in CR lost it. With no terminator, a password ending in LF lost it. An explicit `\r\n` is what gets stripped, so the password's own bytes stay.
  - Why a process substitution and not a pipe: under the script's pipefail, `printf | run …` can fail with SIGPIPE when `run` returns without reading stdin (its dry-run branch).
- **python3 fallback:** the code is a fixed single-quoted string. The password arrives as `printf '%s' "$password" | python3 -c '… sys.stdin.buffer.read() …'`, exact bytes. The `{SSHA}` format is unchanged.
- An existing `docker/auth/htpasswd` is never regenerated (the function returns early), so nothing changes on boxes already installed.

## Files

- `scripts/install/malcolm-config.sh`: `generate_auth`.
- `tests/scripts/test_malcolm_config.bats`: 3 new tests.
- `Debugging/DEPLOYMENT-ISSUES.md`: Chain 34, a Key Files row, a Quick Reference row.

## Test results

- `bats tests/scripts/test_malcolm_config.bats`: 48/48 before, 51/51 after.
- New tests, all with a password holding `'`, `\`, `"`, `$` and spaces, and verbose on:
  1. A stub htpasswd records its arguments and stdin. The password is in neither the arguments nor the output, and stdin is exactly the password plus `\r\n`.
  2. The real htpasswd (skipped if it isn't installed) for that password and for ones ending in CR, LF and CRLF. Each is checked with `htpasswd -vb`, which takes the exact bytes from its arguments.
  3. The python3 fallback, with htpasswd hidden. The password is in neither python3's arguments nor the output, and the `{SSHA}` line verifies against the password's bytes.
- On the old code, tests 1 and 3 fail. Test 2 passes on the old code (`-b` is exact) and fails with `printf '%s'` (no terminator) on `pw\n`, so it pins the framing.
- `shellcheck -S warning scripts/install/malcolm-config.sh`: clean, before and after.
- `daemon/tests/test_malcolm_upgrade.py` (it reads malcolm-config.sh): 30 passed.

## Device (G11)

Read-only checks: no `htpasswd` (so the python fallback ran there); `docker/auth/htpasswd` is 61 bytes, root 600 (the `{SSHA}` form); `/home/nettap` is 750; no `hidepid` on `/proc`; bash 5.2, Python 3.12.

No deploy script: a deploy changes nothing, because the file exists. How a real install proves the fix, on a fresh box or one with `docker/auth` moved aside:
1. Open a root shell with `sudo -i`, so the password is never an argument to sudo.
2. `read -rs NETTAP_ADMIN_PASSWORD; export NETTAP_ADMIN_PASSWORD`, and type a test password with a quote in it.
3. In a second shell, sample `ps -eo args` for a distinctive part of the password.
4. Run `/home/nettap/NetTap/scripts/install/malcolm-config.sh -v`.
5. Neither the output nor the samples may contain the password, and the new `docker/auth/htpasswd` must verify it.

## Lessons

- `htpasswd -i` strips a final LF and the CR before it, even at EOF. Frame stdin with `\r\n` so the password's own trailing bytes survive. Check with `-vb`, not `-vi`, because `-vi` strips the same way and hides the bug.
- `sudo VAR=secret cmd` puts the secret on sudo's command line. Set it in a root shell with builtins.
- `printf | f` under pipefail can fail with SIGPIPE when `f` doesn't read. `f < <(printf …)` can't.
- bats leaves a test's stdin open. A stub that reads stdin needs the call under test run `< /dev/null`, or a regression hangs an interactive run instead of failing it (ponytail review).

## Next steps (found, not changed)

- **Brief file-mode windows.** `.admin-password`, the OpenSearch curlrc and `docker/.env` are written under the default umask and chmod'ed after. With the repo in a 750 home (as on the G11), other accounts can't reach them. A repo elsewhere could expose them for a moment.
- **The file may be dead.** `docker/auth/htpasswd` is unused: no compose service mounts `docker/auth`. The fallback hash is salted SHA-1. Whether to drop `generate_auth` is the owner's call.
- **Standalone dry run.** `malcolm-config.sh --dry-run` still writes files and stops at `chmod` (Known Risk, Chain 33).
- **Nothing else found.** No other `scripts/install/` script passes the admin or OpenSearch password on a command line.
