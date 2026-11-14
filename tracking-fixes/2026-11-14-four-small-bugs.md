# Four small bugs from the Linear bug triage, 2026-11-14

**Linear:** NET-268, NET-256, NET-253, NET-252
**Branch:** `fix/small-bugs-2026-11-14`, one commit per bug
**Status:** built and tested locally. The two daemon fixes deploy with the daemon image. The two
installer fixes only run on a fresh install or when the hardware check is run by hand, so the G11
can't show them without a reinstall.
**Plan gate:** not needed. Each fix is a one-line change.

## NET-268: DNS Lookup read a name like "ns" as a record type

- **Root cause:** `DnsReconService._query` passed `domain, rtype` to dig as bare arguments. dig reads
  a bare word that is also a type or class (`ns`, `mx`, `a`, `any`) as that type, so `dig ns A`
  asked for `. NS`.
- **Fix:** `-q <domain> -t <type>`. The type stays last because eight test fakes read `args[-1]`.
- **Files:** `daemon/services/dns_recon_service.py`, `daemon/tests/test_dns_recon_service.py`.

## NET-256: IoT trust score percentages rounded half to even

- **Root cause:** `_pct` used Python's `round()`, which rounds halves to the even neighbour: 74.5
  became 74 (grade C), 62.5 became 62.
- **Fix:** `int(x + 0.5)`, which is correct because x is clamped to 0–100. Both callers (the
  per-pillar score and the overall score) go through `_pct`.
- **Review follow-up:** `compute_fleet_score` rounded the fleet's harmonic mean the same way (3 and 9
  give exactly 4.5, which read 4). It now rounds halves up too, with a test.
- **Files:** `daemon/services/iot_trust_scorer.py`, `daemon/tests/test_iot_trust_scorer.py`.

## NET-253: validate-hardware.sh run on its own stopped at the first warning

- **Root cause:** under `set -euo pipefail`, `check_x; rc=$?` exits before `rc` is read when a
  check returns 1 or 2. The installer sources the script and calls it under `||`, which turns
  set -e off, so installs were not affected.
- **Fix:** `rc=0; check_x || rc=$?`. The `(( … )) && (( ++n ))` lists were already safe.
- **Files:** `scripts/install/validate-hardware.sh`, `tests/scripts/test_validate_hardware.bats`.

## NET-252: a fresh install's first daily index could get a replica (yellow)

- **Root cause:** `deploy-malcolm.sh` pushed Malcolm's raw `malcolm_template`, which has no replica
  count. Malcolm's own loader later stamps `.template.settings.index.number_of_replicas`, 0 on one
  node (`shared-object-creation.sh` line 110 on the G11). An index created before that stamp got
  OpenSearch's default of 1 replica, which a single node can't place.
- **Fix:** stamp replicas 0 on our push with the same jq expression Malcolm uses. The body is built
  first, so a failed `cat`, `sed` or `jq` (pipefail) sends nothing and warns.
- **Checked on the G11:** the real `/opt/templates/malcolm_template.json` has a top-level `template`
  key with `settings.index` and no replica count.
- **Files:** `scripts/install/deploy-malcolm.sh`, `tests/scripts/helpers/bootstrap_stubs.bash`,
  `tests/scripts/test_deploy_malcolm.bats`.

## Tests

- Each fix has a test that failed against the old code and passes now.
- Daemon pytest: 5014 passed, 5 skipped, 0 failed.
- bats `test_validate_hardware.bats` + `test_deploy_malcolm.bats`: 60 of 60.
- shellcheck on both scripts: clean.

## Reviews

- /ponytail-review: ship, nothing to cut.
- /deep-review: no findings (`security-reviews/fix-small-bugs-2026-11-14/`).

## Lessons

- dig: always pass the name with `-q` and the type with `-t` when the name comes from a user.
- A one-off script run with `set -e` needs `cmd || rc=$?`, not `cmd; rc=$?`.
