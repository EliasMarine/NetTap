# 2026-11-01 — Zeek wrote no logs: AMD RDRAND bug gave every process the same Broker ID

**Status:** Fixed in code; device run pending.
**Linear:** NET-127.
**Branch:** `fix/zeek-rdrand-urandom`, off `fix/daemon-drop-nsenter`.
**Chain:** DEPLOYMENT-ISSUES.md Chain 23.

## What changed
- **zeek-live is built locally.** `docker/Dockerfile.zeek-live` starts from the pinned Malcolm Zeek image (`26.02.0`) and adds `libnettap_urandom.so`. The compose service gets `build:` and `image: nettap/zeek-live:<malcolm tag>`, so the version page still shows the Malcolm tag.
- **The library** (`docker/zeek-live/random_device_urandom.cpp`):
  - replaces libstdc++'s `std::random_device::_M_init`;
  - sends `default`, `rdrand` and `rdseed` to `/dev/urandom`;
  - leaves explicit device files (`/dev/random`) alone.
- **Loaded via `/etc/ld.so.preload`.** zeek has file capabilities, so the loader is in secure mode and ignores LD_PRELOAD.
- **Self-test** (`docker/zeek-live/random_device_urandom_test.cpp`):
  - runs in the build stage with LD_PRELOAD, and again in the final image through the preload file;
  - the final stage also fails the build if `zeek` or `libbroker.so` stop importing the replaced symbol.
- **CI:** a new `zeek-live` docker-build matrix entry builds only the `build` stage (compile and self-test), so the 1.4 GB Malcolm base isn't pulled.
- **Tests:** `test_compose_validation.bats` gets a zeek-live build test. Its host-network test now reads the whole service block (the new `build:` lines pushed `network_mode` past `grep -A5`).
- **Build lists:** `deploy-malcolm.sh` (log line only, it already builds every buildable service) and `verify-release.sh` now include zeek-live.
- **Deploy script:** new `scripts/remote/deploy-zeek-rdrand-fix.sh`.

## Root cause
- On the G11 (AMD Ryzen Embedded R2514), RDRAND returns a constant. The kernel logs `RDRAND is not reliable on this platform; disabling` but only stops using it itself, and CPUID still advertises it.
- libstdc++'s `std::random_device("default")` uses RDSEED/RDRAND, and Broker makes endpoint IDs from it.
- So every Zeek process had ID `001599e4-f730-5365-83be-168f95cf9782`, and Broker refused to peer.
- What that looked like:
  - all zeekctl nodes "running", with zero connections between them;
  - only `cluster.log` written;
  - Malcolm's `zeekdeploy.sh` redeploying every 60-80 s;
  - 0 Zeek records in OpenSearch, against 5,120 from Suricata.

## Steps / solution
1. **Prove the cause.** `Broker::node_id()` was identical across runs while Python's uuid4 varied. A two-process peering test failed under every network and seccomp setup tried.
2. **Choose the fix.** The owner chose the Zeek-only fix: no BIOS, kernel or host change.
3. **Confirm it's feasible in the image.** zeek and libbroker link libstdc++ dynamically and import `_M_init`. Debian 13 trixie, so the build stage uses `debian:trixie-slim`.
4. **Test throwaway Zeek containers with the library:** IDs differ, and peering works as root and as uid 1000.
5. **Build the Dockerfile on the G11.** The self-test passes in both stages. A negative control (the test without the library) fails on all three CPU sources.

## Files touched
- `docker/Dockerfile.zeek-live`, `docker/zeek-live/random_device_urandom.cpp`, `docker/zeek-live/random_device_urandom_test.cpp` (new)
- `docker/docker-compose.yml`
- `.github/workflows/ci.yml`
- `tests/scripts/test_compose_validation.bats`
- `scripts/install/deploy-malcolm.sh`, `scripts/verify-release.sh`
- `scripts/remote/deploy-zeek-rdrand-fix.sh` (new)
- `Debugging/DEPLOYMENT-ISSUES.md`, `Debugging/BRIDGE-ARCHITECTURE.md`

## Test results
- **On the G11:**
  - the build-stage self-test prints `random_device shim: ok`;
  - the negative control exits 1 with 3 FAIL lines;
  - the final-image self-test and symbol checks pass;
  - Broker node IDs differ in the built image.
- **Compose bats:** the new test and the fixed host-network test pass. The other 7 failures are on the base branch too; the suite isn't run in CI.
- **Lint:** `shellcheck -S warning` is clean on the deploy script, `deploy-malcolm.sh` and `verify-release.sh`.
- **Device deploy:** pending. Command: `bash /home/nettap/NetTap/scripts/remote/deploy-zeek-rdrand-fix.sh`.

## Lessons
- **The kernel's RDRAND warning doesn't protect userspace.** Any `std::random_device` user on that CPU gets a constant.
- **"All nodes running, zero connections" in a Broker cluster** means comparing `Broker::node_id()` across two runs first.
- **A binary with file capabilities ignores LD_PRELOAD.** `/etc/ld.so.preload` works.

## Next steps
- **Run the deploy script on the G11.** Then confirm the dashboard fills in.
- **Still open, found while diagnosing:**
  - `event.provider` and `event.dataset` are mapped as text in `arkime_sessions3-*`, so the Malcolm index template may not be applied. Aggregations on them fail.
  - arkime-live keeps logging "Giving opensearch-local time to start...".
  - `config/zeek/nettap.zeek` is mounted at `/opt/zeek/share/zeek/site/local.zeek`, but Zeek reads `/usr/local/zeek/share/zeek/site`, so the override is unused.
  - `update_executor` runs `docker compose pull zeek`, which is not a service name, so Zeek updates from the UI already fail. With zeek-live built locally, an update must rebuild it, not pull.
