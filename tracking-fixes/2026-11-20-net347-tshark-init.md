# NET-347 (A0): the TShark container could not fork

**Date:** 2026-11-20 · **Branch:** `fix/tshark-init` · **Status:** done, verified on the G11 (PR #345 → 65e1bc71)

## What changed
- `docker/docker-compose.yml`: `init: true` on `nettap-tshark`.
- `scripts/remote/deploy-tshark-init.sh`: recreates only `nettap-tshark` (`--no-deps`, no build) and checks the fix on the device.
- `Debugging/DEPLOYMENT-ISSUES.md` Chain 38, a Known Risks row, and a `Debugging/RELIABILITY-TRACKER.md` row.

## Root cause
The image's entrypoint `tail -f /dev/null` was PID 1 and never reaped. Every supervised job (`container_exec.py` SUPERVISOR) left its watchdog `sh` and `sleep` orphaned to PID 1. On the G11 after 11 days: 14,136 zombies, cgroup `pids.current 14137` of `pids.max 14138`. Every fork failed, so PCAP Search reported "311 files couldn't be searched: timeout: fork system call failed".

## Steps / solution
1. Confirmed on the G11, read-only: `docker stats` PIDs 14137, `cgroup.procs` 1 (zombies leave it but keep their pid charge), host `ps` showed `Z` children of the container's `tail`.
2. One-line fix: Docker's init (tini) reaps every orphan. A SUPERVISOR change can't do it: the killed watchdog's `sleep` grandchild is orphaned to PID 1 anyway.
3. The deploy recreates only this container. It holds no data, and OpenSearch is untouched.

## Test results
- `shellcheck scripts/remote/deploy-tshark-init.sh`: clean.
- `docker compose config` renders `init: true` for `nettap-tshark`.
- Device (2026-11-20, `deploy-tshark-init.sh`): before, pids 14137/14138 and 14,136 zombies. After: `HostConfig.Init` true, PID 1 `docker-init`, closed capture read (frame 1), 20 of 20 checks answered 200, 0 zombies, pids.current 2. Every check passed.

## Lessons
- A container driven by `docker exec` needs a PID 1 that reaps.
- `docker top` hides zombies. Read the cgroup's `pids.current` instead.

## Next steps
PR A (`fix/pcap-search-reliability`): check the filter before a search, bound live readers across replacements, and show incomplete results honestly.
