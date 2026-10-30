# DHCP Gateway Capture Mode (2026-10-30)

**Status:** Code complete, gates green locally. Not run on hardware.
**Type:** feat (+ fixes for review findings CR-007, CR-165, CR-166, CR-167, CR-212, CR-247)
**Branch:** `phase-4/dhcp-gateway-mode` → `fix/pr110-review`, [PR #145](https://github.com/EliasMarine/NetTap/pull/145) (`develop` no longer exists, so this PR is stacked like #143 and #144)
**Linear:** NET-111 (feature), NET-112 (review)
**Design:** `docs/plans/2026-10-30-dhcp-gateway-mode-design.md`
**Architecture:** `Debugging/BRIDGE-ARCHITECTURE.md` §16
**Review:** `docs/reviews/2026-10-30-code-review.md` (branch `chore/code-review-2026-10`, [PR #146](https://github.com/EliasMarine/NetTap/pull/146))

## Problem
- NetTap's inline bridge sits between the modem and the router, outside the router's NAT. It only sees the router's public IP, so it can't say which device did what.
- Mirror-port mode needs a managed switch, which most homes don't have.
- The capture mode and NIC picked in the wizard never reached Zeek, Suricata or Arkime (CR-007). Every install captured on the default interface whatever the user chose.

## Root causes
- No capture mode put NetTap on the LAN side of NAT without extra hardware.
- The daemon saved capture config inside its own container. The capture containers had a fixed `PCAP_IFACE` and never read it.

## Fix
**New mode, `dhcp_gateway` (one-armed, own subnet + NAT):**
- dnsmasq, run by the daemon in DHCP-only mode (`--port=0`) as `nobody`, hands out NetTap's own subnet (default `10.77.0.0/24`). The DNS option points at the router.
- iptables: `DOCKER-USER` ACCEPT pinned to `-i <lan> -o <lan>`, `POSTROUTING` MASQUERADE, `OUTPUT` ICMP-redirect drop. All rules are tagged `nettap-dhcp-gateway`. The backend (nft or legacy) is whichever one holds `DOCKER-USER`.
- NetTap keeps its own address once the router's DHCP is off: a netplan static file, a 30 s `reconcile()` that self-heals, and a boot unit (`nettap-dhcp-gateway.service`, After=docker) with the wants-symlink pointing at the host path.
- Safety: a DHCPDISCOVER probe always runs before dnsmasq starts. If another server answers, DHCP is saved as off. If the probe errors, DHCP is held off for that tick only. Leaving an active gateway returns 409 unless another DHCP server answers. Bridge create returns 409 while the gateway is routing. Mirror mode refuses a NIC that has an IPv4, the default route, or the gateway NIC.
- Capture filter: `net <subnet> or udp port 67 or udp port 68`, so only the device leg is captured, not a NAT'd duplicate.

**Capture-mode plumbing (CR-007):** host `/etc/nettap` is mounted rw into the daemon and ro into the capture containers. `capture.env` is parsed (never sourced) and validated by `config/capture/nettap-capture-env.sh`, which exports `PCAP_IFACE`, `PCAP_FILTER` and `CAPTURE_FILTER`. Capture containers restart only when the file changes.

**Web:** the wizard shows DHCP gateway (Recommended) and Mirror port first; the inline bridge sits under "Advanced". Go Live has a DHCP view with preflight checks, router-DHCP guidance and a sortable lease table. Mode labels fixed in the layout badge, System and Infrastructure (CR-212, CR-247). Enable, disable and configure proxies wait 60 s.

## Files
- Daemon (new): `services/dhcp_probe.py`, `dhcp_gateway.py`, `dhcp_gateway_net.py`, `dhcp_gateway_host.py`, `dhcp_gateway_preflight.py`, `dhcp_gateway_runtime.py`, `api/dhcp_gateway.py`
- Daemon (changed): `api/setup.py`, `api/bridge.py`, `api/capture_control.py`, `api/server.py`, `main.py`, `services/capture_config.py`, `services/capture_manager.py`, `services/capture_mode_stub.py`
- Docker: `docker/Dockerfile.daemon` (iptables, dnsmasq-base), `docker/docker-compose.yml` (caps, `/etc/nettap` mounts, capture entrypoints), `config/capture/nettap-capture-env.sh`
- Web (new): `lib/api/dhcpGateway.ts`, `lib/utils/dhcpSubnet.ts`, `lib/components/setup/DhcpGatewayStep.svelte`, `lib/components/golive/DhcpGoLive.svelte`, `routes/api/capture/dhcp/{enable,disable}/+server.ts`
- Web (changed): `routes/setup/+page.svelte`, `routes/go-live/+page.svelte`, `routes/+layout.svelte`, `routes/system/+page.svelte`, `routes/infrastructure/+page.svelte`, `lib/components/CaptureHealthPanel.svelte`, `lib/api/capture.ts`, `lib/stores/captureMode.ts`, `routes/api/setup/configure/+server.ts`
- Device: `scripts/remote/deploy-dhcp-gateway-mode.sh`
- Tests: listed in the commits; bats in `tests/scripts/test_capture_env_loader.bats`

## Test results
- pytest: 2315 passed
- ruff check and format: clean
- vitest: 152 files, 1942 passed
- svelte-check: 0 errors
- `tests/scripts/test_capture_env_loader.bats`: 10/10
- `tests/scripts/test_compose_validation.bats`: the new tests pass; 7 older tests (2, 6, 10, 11, 13, 19, 29) fail on the base commit too and are not touched here
- `docker compose config`: OK; `bash -n` on the deploy script: OK

## Reviews
- Build review found 6 must-fix items (unpinned `DOCKER-USER` rule, dnsmasq without a probe, wizard teardown cutting off the LAN, mirror NIC lockout, enable outlasting the 10 s proxy timeout, router-DHCP guide shown wrongly). All fixed.
- Fix verification found 3 more (probe error saved "off", bridge 409 keyed on config not live routing, a failed re-enable shown as success). All fixed, each with a test.

## Device verification
```bash
bash scripts/remote/deploy-dhcp-gateway-mode.sh
```
It rebuilds and recreates the daemon, web and the four capture containers (never OpenSearch), checks health, and runs token-authenticated GETs only. It never turns DHCP gateway mode on.

## Not verified
Real dnsmasq in the built image, iptables against the host's Docker, the netplan merge, latency under load, specific router models, and a full reboot with DHCP mode on.

## Lessons
- A config file the daemon writes inside its own container reaches nobody. Check the reader can see it before calling a setting "applied".
- Docker's FORWARD policy is DROP. Host routing goes in `DOCKER-USER`, pinned to exact interfaces.
- Probe before you serve DHCP. A transient probe error should hold, not save "off".

## Next steps
- Run the device script, then a supervised DHCP-mode trial on the N100.
- Switch capture mode after first run (today it's wizard-only).
- Review LD-001: `bridge_manager.py` and `mirror_manager.py` create their boot wants-symlinks with the container path, so those units never start at boot.
- CR-025 / MS-001: a reboot runs `compose down` and recreates OpenSearch, which then needs the security bootstrap. That hits DHCP mode too.
- IPv6 bypasses the gateway; devices with static IPs aren't captured; double NAT for anything that needs port forwarding.
