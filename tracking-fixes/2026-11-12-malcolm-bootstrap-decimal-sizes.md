# Malcolm bootstrap fails loudly; installer sizes in decimal GB, 2026-11-12

**Linear:** NET-217, NET-177
**Branch:** `fix/malcolm-bootstrap-and-decimal-sizes`
**Status:** built and tested locally. The read-only checks on the G11 pass. The device check (`scripts/remote/deploy-malcolm-bootstrap.sh`) is still to run.
**Plan:** Codex review, 4 rounds, APPROVED. The plan is in `.codex-review/2026-11-12-174005-malcolm-bootstrap/` (gitignored).

## Why

`scripts/install/deploy-malcolm.sh` sets up OpenSearch's login and index templates. The normal install runs it, and so does `activate-bridge.sh` (since NET-216). Its bootstrap had two problems:
- **It warned and carried on when a step failed.** An install could report success with no working login or no templates, and every page then stayed empty (Chains 11 and 28).
- **It put the OpenSearch password on the command line.** It read the curlrc on the host, then ran `docker compose exec … curl -u "malcolm_internal:<password>"`. Any local account could read the password from `ps` while it ran.

Separately, the installer printed GiB labelled "GB". A 1 TB drive read "931 GB". The daemon and the web app have used decimal GB since NET-166.

## What changed

**NET-217: `scripts/install/deploy-malcolm.sh`**
- **No password in any argument.** Every OpenSearch call from dashboards-helper goes through `_helper_curl`, which reads the login from the curlrc that container already mounts (`curl --config /var/local/curlrc/.opensearch.primary.curlrc`). The host-side read of the curlrc and every `-u "$os_creds"` are gone.
- **Every request has a time limit.**
  - dashboards-helper calls: `--connect-timeout 10 --max-time 60`.
  - The auth probe and the HTTP wait: `--max-time 10`.
  - securityadmin.sh runs under `timeout -k 10 180` inside the opensearch container. Killing the docker CLI would leave it running.
- **The security bootstrap stops the run.** A failed securityadmin.sh (2 tries), or a login that still fails 30 s after it, calls `error`. The message says what failed, what to check, and "run the same command again". Before, the second case only warned.
- **The template bootstrap stops the run.** One pass is `_push_index_templates`, run up to 3 times, 10 s apart. Then `error`. A pass:
  - Reads malcolm_template.
    - If it already targets `arkime_sessions3-*`, it is left as Malcolm's loader tuned it: `_meta.hash`, replicas 0, refresh 1s. Re-pushing the raw file used to undo that until the loader's next run, about 2 minutes. Any daily index created in between kept a replica a single node can't place.
    - The answer is parsed with jq inside dashboards-helper. A failed or unreadable read writes nothing.
  - Pushes the component templates and malcolm_template only when malcolm_template is absent or targets another pattern (Chain 24). Any non-200 fails the pass. So does an empty file list, which happens when dashboards-helper isn't ready; the old code then silently pushed nothing.
  - Writes the Arkime marker with `PUT _template/arkime_sessions3_template?create=true`. OpenSearch refuses that with HTTP 400 when any template of that name exists, so Arkime's real template is never replaced.
  - Checks that both templates exist: Logstash waits for malcolm_template, dashboards-helper for arkime_sessions3_template.

**NET-217: `scripts/install/ui.sh`.** The failure hint for "Deploying Malcolm stack" now reads "Read the error above. For a failed image pull: curl -sI https://ghcr.io". Before, it always pointed at the image registry.

**NET-177: decimal GB**
- **`validate-hardware.sh` check_disk.**
  - Size: `disk_kb * 1024 / 10^9`. A 1 TB filesystem now reads "1000 GB total".
  - Threshold: `MIN_DISK_GB=430`. The old 400 GiB is 429.5 GB, so the minimum is 0.1 % stricter: effectively unchanged.
  - The OK line says "GB total". System shows the smaller usable size (used + free, without root-reserved blocks): 1965 vs 1884 GB on the G11.
- **`deploy-malcolm.sh` preflight free space.**
  - Size: `df -k` × 1024 / 10^9, the same quantity as System's `disk_free_gb`.
  - Threshold: warn below 15 GB. GNU `df -BG` rounds up, so the old `< 15` meant 14 GiB or less, about 15.03 GB.

**Who runs this, and what happens on failure**
- **`install.sh` step 5:** the install stops. The failure card names step 5 and says to run the same command again.
- **`activate-bridge.sh`:** it exits nonzero after the bridge is up. The `error` line is the last thing shown. It can be re-run.
- **The in-app Malcolm update (`daemon/services/malcolm_upgrade.py`):** it does **not** run deploy-malcolm.sh, so it is unaffected. It runs compose itself, checks its own login, and rolls back on failure. The templates live in the OpenSearch data volume.

## Files

- `scripts/install/deploy-malcolm.sh`
- `scripts/install/validate-hardware.sh`
- `scripts/install/ui.sh`
- `scripts/remote/deploy-malcolm-bootstrap.sh` (NEW): the device check.
- `tests/scripts/test_deploy_malcolm.bats`: 19 new tests. The old #73 grep test is kept as OLD CODE.
- `tests/scripts/helpers/bootstrap_stubs.bash` (NEW): a fake docker that plays dashboards-helper and opensearch.
- `tests/scripts/test_validate_hardware.bats` (NEW)
- `Debugging/DEPLOYMENT-ISSUES.md`: Chain 31.

## Test results

- **bats, before:**
  - test_deploy_malcolm 37/37;
  - test_install_ui 33/33;
  - test_activate_bridge 9/9;
  - test_install 1/1.
- **bats, after (with the PR #251 review fixes):**
  - test_deploy_malcolm 55/55;
  - test_validate_hardware 2/2;
  - test_install_ui 33/33;
  - test_activate_bridge 9/9;
  - every other `tests/scripts/*.bats` file still passes.
- All 19 new tests fail on the old code except one: "auth that works after securityadmin.sh" is a regression guard and passes on both.
- `shellcheck -S warning` over every `scripts/**/*.sh` (as CI runs it) is clean.

## Device (G11)

**Read-only checks already done, 2026-11-12:**
- auth 200;
- malcolm_template targets `arkime_sessions3-*` and carries `_meta.hash`;
- arkime_sessions3_template is NetTap's marker;
- 53 component templates = 42 ECS + 11 custom files;
- the dashboards-helper exec user is root, the curlrc is mounted, curl is 8.14.1 and jq is 1.7;
- `timeout` is GNU 8.32 in the opensearch container.

The new read functions were run there read-only:
- `_opensearch_auth_ok` passes;
- `_malcolm_template_state` keeps the live template and would push one with the placeholder pattern;
- both acceptance GETs pass;
- an unauthenticated read gets 401.

**Still to run, by the lead:** `bash scripts/remote/deploy-malcolm-bootstrap.sh`. It rebuilds and recreates nothing. Its `guarded_docker` is an allowlist: preflight's `docker info` and `compose version`; curl reads, jq, cat and find inside opensearch and dashboards-helper; and the create-only marker PUT. It skips `compose up -d dashboards-helper` and refuses everything else. It proves:
- (a) the real bootstrap exits 0, auth works, both templates are present and unchanged, and malcolm_template is kept;
- (b) while it runs, no `ps -ww -eo args` sample contains the password, and some samples show its `curl --config` calls;
- (c) a forced failure (no credentials) exits nonzero with "Index template bootstrap failed after 3 attempts", and nothing changed;
- validate-hardware prints decimal GB;
- opensearch and dashboards-helper were not restarted.

## PR #251 review fixes

The lead's review found five things. All are fixed, each with a test that fails on the code before it:
- **Bare `! grep` assertions never failed.** Bats runs tests under `set -e`, which ignores a negated command. The four such lines now end in `|| false`. Reintroducing `-u "admin:secret"` in `_helper_curl` now fails two tests.
- **The keep check could be fooled.** `jq .[]` printed each pattern on its own line, so a pattern like `"zz\narkime_sessions3-*"` matched `grep -x`. jq now checks that one entry equals the pattern exactly. The template must also carry `_meta.hash`, which only Malcolm's loader stamps, so the raw file we pushed is pushed again until Malcolm takes over. Checked read-only on the G11: the live template gives `keep`.
- **The device check's guard was a denylist.** `-XPUT` and `compose restart` got through. `guarded_docker` is now an allowlist (see above).
- **The waits counted sleeps, not time.** With each probe's own 10 s limit, "120s" could run for about 6 minutes. The HTTP wait and both auth waits now use `$SECONDS`. securityadmin.sh gets 2 tries, not 3. The messages state the real limits.
- **A failed PUT dropped OpenSearch's reason.** `_helper_put` now keeps the response body and adds its first 200 characters, on one line, to the warning.

`--dry-run` still runs these helpers, so it writes. That is out of scope here; it is NET-211 #8, owned by the installer agent.

## Lessons

- A retry count only bounds time when each try has a time limit (`--max-time`, `timeout -k`). A wait only bounds time when it counts wall-clock time (`$SECONDS`), not sleeps.
- In bats, a bare `! cmd` never fails a test. Write `! cmd || false`.
- A guard that must stop writes is an allowlist. A denylist misses the writes nobody thought of.
- "Read failed" must never look like "absent" to code that writes on absence. Parse the answer and fail closed.
- Prefer OpenSearch's create-only flags to a GET-then-PUT.
- `docker compose exec` reads stdin. A script piped into `bash -s` loses the rest of itself to the first exec. Give such calls `< /dev/null`, or don't feed scripts on stdin.

## Next steps (found, not changed)

- **A fresh install's first malcolm_template carries no tuned settings.** The first daily index can get OpenSearch's default replica count before Malcolm's loader stamps the template. This predates the change.
- **`scripts/install/malcolm-config.sh:135` and `:142` put the nginx-proxy admin password on the command line:** `htpasswd -bcB … "$password"`, and a `python3 -c` with the password embedded.
- **`validate-hardware.sh` run standalone stops at the first warning or failure.** It runs under `set -e`, and `check_x; rc=$?` exits there. On the G11 it stops at the RAM warning before the disk line. The installer sources it, so it is unaffected.
