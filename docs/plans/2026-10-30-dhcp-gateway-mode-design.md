# DHCP Gateway Capture Mode — Design

**Date:** 2026-10-30
**Status:** Approved for implementation (owner decisions locked 2026-10-30)
**Branch:** `phase-4/dhcp-gateway-mode` (stacked on `fix/pr110-review`, PR #144)
**Related:** `Debugging/BRIDGE-ARCHITECTURE.md`, memory `dhcp-gateway-mode`

---

## 1. Why

The inline bridge sits between the ISP modem and the router, so it only sees
traffic **after** the router's NAT. Every device shows up as the router's
public IP, so NetTap can't answer "what is each of my devices doing?".

DHCP gateway mode puts NetTap in front of the router's NAT. NetTap hands out
addresses, names itself as the gateway, and routes traffic on to the real
router. Every flow then carries the device's real IP and MAC. It works on any
router and needs no managed switch. Firewalla's DHCP mode works the same way.

## 2. Owner decisions (locked)

| Decision | Choice |
|----------|--------|
| Onboarding modes | **DHCP gateway** (recommended) and **Mirror port** are primary. The inline bridge stays under "Advanced". No bridge code is removed. |
| One-way traffic fix | NetTap serves its **own subnet** (default `10.77.0.0/24`) and **masquerades** to the router (double NAT). The only router change: turn off the router's DHCP. |
| Review findings | Listed only. Code that this work rewrites must not carry a finding forward. |

## 3. Topology (one-armed)

```
                  ISP modem
                      │
              ┌───────┴────────┐
              │  Home router   │  192.168.1.1/24  (DHCP OFF)
              └───────┬────────┘
                      │ LAN port / switch / router Wi-Fi
     ┌────────────────┼──────────────────────────┐
     │                │                          │
  NetTap LAN NIC   phone, TV, laptop ...      static-IP devices
  192.168.1.50/24  10.77.0.x/24                (bypass NetTap)
  10.77.0.1/24     gw = 10.77.0.1
                   dns = 192.168.1.1
```

- One NIC (the one plugged into the router) carries both legs:
  device ↔ NetTap (`10.77.0.x`, pre-NAT) and NetTap ↔ router (`192.168.1.50`,
  post-NAT). A 2.5GbE port gives each direction plenty of headroom for a WAN of
  1 Gbps or less.
- Devices on Wi-Fi from the router's own access point are covered too, because
  DHCP and the gateway are L3, not tied to a cable.
- NetTap keeps its existing address on the router subnet (`192.168.1.50`
  above), so the dashboard URL does not change. That address becomes
  **static**, because nothing will renew it once the router's DHCP is off.

## 4. Mechanisms

### 4.1 DHCP server: dnsmasq, run by the daemon

- `dnsmasq-base` is added to the daemon image. The daemon already runs with
  `network_mode: host`, NET_ADMIN and NET_RAW. Add **NET_BIND_SERVICE** (UDP
  67), **SETUID** and **SETGID** (dnsmasq drops to `nobody:nogroup`) and
  **KILL** (the root daemon can only signal the `nobody`-owned dnsmasq with it)
  to its `cap_add`.
- DHCP only: `--port=0` disables DNS. NetTap is **not** a DNS server.
  Option 6 (DNS) hands out the **router's IP**. DNS queries still pass through
  NetTap as the gateway, so Zeek's `dns.log` attributes them to the real
  device. This also means a daemon restart never breaks name resolution.
- Arguments (no config file):
  `--keep-in-foreground --port=0 --conf-file=/dev/null --pid-file
  --user=nobody --group=nogroup --interface=<lan> --except-interface=lo --bind-interfaces
  --dhcp-authoritative --dhcp-range=<pool_start>,<pool_end>,<netmask>,1h
  --dhcp-option=option:router,<gateway_ip>
  --dhcp-option=option:dns-server,<upstream_gateway>
  --dhcp-leasefile=/var/lib/nettap/dhcp/dnsmasq.leases --log-facility=-`.
  dnsmasq must not run as root: it opens its sockets and the lease file as
  root, then drops to `nobody:nogroup` (uid/gid 65534 in the
  `python:3.12-slim-bookworm` image), keeping only NET_ADMIN and NET_RAW.
  The lease file stays **root-owned**: root in the container has no
  DAC_OVERRIDE, so a `nobody`-owned file would stop dnsmasq opening it. The
  already-open file is still written after the drop. `--pid-file` with no
  value writes no pid file (the daemon supervises the child; as `nobody`,
  dnsmasq can't chown one in `/var/run`). Verified in the image with
  `cap_drop: ALL` and exactly the capabilities above: a client got a lease
  and it was written to the file.
- Pool: host offsets 10 … last-host (`10.77.0.10–10.77.0.254` for a /24).
  `.1` is the gateway, `.2–.9` are left for the user's static assignments.
- **Lease time: 1 hour.** Rollback (router DHCP back on, NetTap DHCP off)
  completes within one lease at worst. Renewals every 30 min per device are
  negligible traffic. A daemon outage shorter than a lease is invisible to
  clients.
- The lease file lives on the `storage-data` volume (`/var/lib/nettap`), so it
  survives restarts.
- The daemon supervises the child: `reconcile()` restarts it if it exited.

### 4.2 Routing and NAT

Runtime (daemon, host network namespace, existing `nsenter -t 1 -n` pattern):

1. `ip addr add <gateway_ip>/<prefix> dev <lan>`, if missing.
2. Re-assert the upstream address and default route if missing (see §4.4).
3. Firewall rules, all tagged `-m comment --comment nettap-dhcp-gateway` and
   added only after a `-C` check (idempotent):
   - `filter DOCKER-USER  -i <lan> -o <lan> -s <subnet> -j ACCEPT`
   - `filter DOCKER-USER  -i <lan> -o <lan> -d <subnet> -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT`

   Both are pinned to `-i <lan> -o <lan>` (the one-armed path). Without `-o`,
   the accept would end FORWARD before Docker's own chains run, and every LAN
   device could reach unpublished container ports (Redis, OpenSearch) on the
   Docker bridges. Published ports (nginx 80/443) still work through Docker's
   DNAT rules. All rules are inserted with `-I`.
   - `nat    POSTROUTING  -o <lan> -s <subnet> ! -d <subnet> -j MASQUERADE`
   - `filter OUTPUT       -o <lan> -p icmp --icmp-type redirect -j DROP`
4. `ethtool -K <lan> gro off lro off` (accurate capture; failure is only a warning).

**Why DOCKER-USER:** Docker sets the `FORWARD` policy to `DROP`. An accept
rule in our own nft table doesn't help, because every base chain on the hook
must accept. `DOCKER-USER` is the chain Docker documents for user rules. It is
jumped to first and Docker never flushes it.

**Why drop ICMP redirects:** in-interface == out-interface on a one-armed
router, so Linux would send redirects telling devices to go straight to the
router. `/proc/sys` is read-only inside the container, so the runtime fix is
the OUTPUT drop rule. `send_redirects=0` is persisted for boot (§4.5).

**Firewall backend detection:** `iptables` is added to the daemon image
(Debian ships both `iptables-nft` and `iptables-legacy`). Use whichever
backend has a `DOCKER-USER` chain (`<cmd> -w -S DOCKER-USER` exits 0), trying
nft first. If neither has one, the backend is `null`, which is a **blocking**
preflight failure. That is conservative: we never guess which table Docker's
DROP policy lives in.

**IP forwarding:** Docker already sets `net.ipv4.ip_forward=1`. Preflight
reads `/proc/sys/net/ipv4/ip_forward`. `0` is a blocking failure, because the
container can't write `/proc/sys`.

### 4.3 Capture: device leg only, exactly once

Each routed flow crosses the LAN NIC twice: the device leg and the post-NAT
router leg. Capture is limited to the device leg with a BPF filter:

```
PCAP_FILTER = "net <subnet> or udp port 67 or udp port 68"
```

DHCP broadcasts (src `0.0.0.0`) are kept for Zeek's `dhcp.log`
(hostname ↔ MAC ↔ IP).

Confirmed against the Malcolm v26.02.0 source:

| Tool | Reads the filter from | Notes |
|------|-----------------------|-------|
| Arkime | `PCAP_FILTER` → `bpf=` in config.ini (`arkime/scripts/docker_entrypoint.sh:132`) | works |
| Suricata | `CAPTURE_FILTER`/`PCAP_FILTER` → af-packet `bpf-filter` (`suricata_config_populate.py:883-892`) | works |
| netsniff-ng (pcap-capture) | `PCAP_FILTER` | works |
| Zeek | `zeekdeploy.sh` exports `CAPTURE_FILTER` from `PCAP_FILTER`; **Malcolm's `local.zeek`** turns it into `restrict_filters` (`getenv("CAPTURE_FILTER")`, the fix for Malcolm issue #474, now closed) | works. The review (CR-091) found that NetTap's `config/zeek/nettap.zeek` mount targets `/opt/zeek/...` while the image installs Zeek to `/usr/local/zeek`, so Malcolm's own `local.zeek`, with its filter hook, is what runs. **Do not touch `nettap.zeek` in this work.** CR-091 tracks the dead mount. |

**Getting the interface and filter to the capture containers.** Today
`PCAP_IFACE` comes only from compose interpolation (`docker/.env`), which the
daemon can't write. That is why the wizard's mirror choice never takes effect
(the "capture settings have no effect" follow-up from PR #144). Fix:

- Bind-mount the host directory **`/etc/nettap`**: read-write into the daemon
  at `/etc/nettap`, read-only into `zeek-live`, `suricata-live`, `arkime-live`
  and `pcap-capture`. That is the default path `capture_config.py` already
  uses for `capture-mode.conf` and `capture.env`.
- `config/capture/nettap-capture-env.sh` (mounted read-only into each capture
  container) parses `/etc/nettap/capture.env` **without sourcing it**. It
  exports only `PCAP_IFACE`, `PCAP_FILTER` and `CAPTURE_FILTER` (same value as
  `PCAP_FILTER`), and only when the file exists. Each capture entrypoint
  wrapper runs `. /usr/local/bin/nettap-capture-env.sh` before `exec tini`.
  When the file is missing, the compose env stays in effect, so existing
  installs are unchanged.
- The daemon writes `capture.env` atomically (temp file + rename) and restarts
  the four capture containers through the existing `capture_control._docker_cmd`
  helper (docker CLI over the socket the daemon already mounts). A restart
  re-runs the entrypoint, which re-reads the file. Containers are never created
  or removed.
- Values are validated before they are written: interface
  `^[A-Za-z0-9._-]{1,15}$`; the subnet is parsed with `ipaddress`; the filter
  is built only from the validated subnet.

### 4.4 NetTap's own address (the router DHCP is about to go away)

Once the router's DHCP is off, systemd-networkd can't renew NetTap's lease.
When the lease expires it removes the address and the DHCP default route, and
NetTap stops routing. The daemon can't run `netplan apply` (no host mount
namespace, no D-Bus), so:

1. **On enable**, record the current upstream address (`192.168.1.50/24`) and
   gateway (`192.168.1.1`) in `capture-mode.conf`.
2. **Persist for boot:** `/etc/netplan/90-nettap-dhcp-gateway.yaml` (mode
   0600) sets the LAN NIC to `dhcp4: false`, with addresses
   `[upstream, gateway_ip/prefix]`, a default route via the upstream gateway,
   and the upstream gateway as nameserver.
3. **Self-heal at runtime:** `reconcile()` runs every capture-health interval
   (30 s). It re-adds the upstream address and the default route if networkd
   removed them, re-adds the gateway address and firewall rules, and restarts
   dnsmasq if it died. If networkd drops the address when the old lease
   expires, routing blips for at most one interval.
4. **Recommended:** reboot NetTap once after activation. Netplan then applies,
   networkd stops running DHCP on the LAN NIC, and the blip can't happen. The
   go-live page says so. NetTap's own outbound DNS (feeds, GeoIP updates) may
   fail between lease expiry and that reboot. Clients are unaffected, because
   they use the router for DNS directly.
   **Caveat (review CR-025):** installs that use `nettap.service` run
   `docker compose down` on stop, so a reboot recreates OpenSearch and its
   security mapping reverts. Until CR-025 is fixed, run the OpenSearch security
   bootstrap from CLAUDE.md after any reboot. The go-live copy links to it.

### 4.5 Boot persistence (no dependency on the daemon starting)

The daemon only starts after OpenSearch is healthy, which can take minutes on
an N100. Routing must come back before that:

| File (host path) | Purpose |
|------------------|---------|
| `/etc/netplan/90-nettap-dhcp-gateway.yaml` | static upstream address, gateway address, default route |
| `/etc/sysctl.d/99-nettap-dhcp-gateway.conf` | `ip_forward=1`, `send_redirects=0` (all, default, `<lan>`) |
| `/etc/nettap/dhcp-gateway-firewall.sh` (0755) | idempotent host-`iptables` rules (same rule list as runtime). Waits up to 60 s for `DOCKER-USER` |
| `/etc/systemd/system/nettap-dhcp-gateway.service` | oneshot, `After=docker.service`, runs the script. Enabled via a symlink in `multi-user.target.wants` whose target is the **host** path `/etc/systemd/system/nettap-dhcp-gateway.service` |

The host's own `iptables` uses the same backend as the host's Docker, so the
boot script needs no backend detection. dnsmasq starts with the daemon, a few
minutes after boot. Clients renewing mid-lease don't notice. New devices wait
until the daemon is up.

> Existing bug noted for the review table as LD-001 (not fixed here):
> `BridgeManager` and `MirrorManager` create their `multi-user.target.wants`
> symlinks with the **container** path (`/host/etc/systemd/system/...`) as the
> target. On the host those symlinks dangle, so their units are never enabled.
> The DHCP unit uses the host path.

### 4.5.1 Review findings this work must not carry forward

These sit in code this feature rewrites, so the rewrite fixes them. Commits
cite the IDs.

| ID | What the rewrite does |
|----|-----------------------|
| CR-007 | The wizard's mode and NIC choice reach `load_capture_config` (INI at `/etc/nettap/capture-mode.conf`) and the capture containers (`capture.env` + restart) |
| CR-165, CR-166 | `/api/setup/configure` validates interface names (`^[A-Za-z0-9._-]{1,15}$`) and the DHCP subnet before writing anything |
| CR-167 | `main.py` starts the storage and SMART loops before capture setup, and wraps capture config load and manager setup in try/except with a logged fallback, so a bad `capture-mode.conf` can't crash-loop the daemon |
| CR-212, CR-247 | `CaptureHealthPanel` and the Infrastructure page label `dhcp_gateway` correctly instead of showing bridge/br0 |

Related findings **not** fixed here, but relevant to operators of this mode:
CR-075 (the rogue-DHCP detector flags clients; nothing consumes it yet),
CR-025 (reboot recreates OpenSearch), CR-091 (dead `nettap.zeek` mount),
CR-114 (the capture-mode store loads once per session).

### 4.6 Safety

| Risk | Mitigation |
|------|-----------|
| Two DHCP servers on one LAN | Preflight sends a real DHCPDISCOVER (AF_PACKET, broadcast flag, 3 s listen) and lists every server that answers. Enable is **refused (409)** while any server other than NetTap answers, and the probe runs again inside `enable`. dnsmasq is **never started without a probe**, at daemon start and in `reconcile()` alike. If another server answers, the DHCP setting is saved as off and the issue is shown. If the probe errors, NetTap holds DHCP off for that tick only and probes again on the next one, because the router's DHCP is off by design. Leaving an active gateway in the wizard is refused (409) until another DHCP server answers. |
| Subnet collides with an existing network | Checked against every IPv4 network on every host interface (router subnet, docker0, br-*). Blocking. |
| NetTap down ⇒ no internet | Stated plainly before enabling (explicit confirmation). Kernel forwarding and NAT survive daemon crashes. The boot unit restores routing without the daemon. The recovery steps are shown on the go-live page and in this doc (§7). |
| IPv6 bypass | If the router advertises IPv6 (RA), devices get global IPv6 and the router as their v6 gateway, so that traffic bypasses NetTap. Detected from a `proto ra` default route or a dynamic global address on the LAN NIC. **Warning, not blocking**, with advice to turn off IPv6 on the router for full visibility. |
| Static-IP devices / mesh routers that can't disable DHCP | Wizard and go-live copy. If the router can't turn DHCP off, the re-probe keeps failing and the UI recommends Mirror or the Advanced bridge. |
| Double NAT | Documented: router port forwards and UPnP don't reach devices, and consoles may report strict NAT. A NetTap-side port-forward UI is a follow-up. |
| Device-to-device LAN traffic | Devices on `10.77.0.0/24` share L2 and talk directly, so that traffic stays invisible (needs Mirror). |

### 4.7 Latency and throughput

The extra L3 hop costs tens of µs (typical, unmeasured), the same order as the
bridge and well under the 1 ms budget. The real risk is jitter while
Zeek/Suricata/Arkime saturate the N100. The remote script measures host→router
and host→1.1.1.1 RTT with capture running, and prints the `iperf3` command to
run from a client for throughput. This can't be verified from the dev machine.

## 5. State and config

`/etc/nettap/capture-mode.conf` (INI, read by `load_capture_config`, written
by `save_capture_config`):

```ini
[capture]
mode = dhcp_gateway
interface = enp1s0
management =

[bridge]
wan_interface = eth0
lan_interface = eth1

[dhcp_gateway]
subnet = 10.77.0.0/24
upstream_address = 192.168.1.50/24     ; set by enable, empty until then
upstream_gateway = 192.168.1.1         ; set by enable, empty until then
dhcp_enabled = false                   ; DHCP server on/off
```

- **Routing active** ⇔ `mode == dhcp_gateway` and `upstream_gateway` set.
- **DHCP server running** ⇔ routing active and `dhcp_enabled`.
- `disable` turns off only the DHCP server. Routing stays, so devices holding
  `10.77.0.x` leases keep working until they move back to the router (within
  one lease, or on reconnect).
- Switching to another mode in the wizard calls `teardown()`: stop dnsmasq,
  delete the rules, remove the gateway address, delete the four boot files.
  The UI warns to turn the router's DHCP back on **before** rebooting NetTap.

`/etc/nettap/capture.env` (consumed by capture containers):

```
CAPTURE_MODE=dhcp_gateway
PCAP_IFACE=enp1s0
PCAP_FILTER=net 10.77.0.0/24 or udp port 67 or udp port 68
```

(mirror: `PCAP_IFACE=<mirror nic>`, `PCAP_FILTER=`; bridge: `PCAP_IFACE=br0`,
`PCAP_FILTER=`.)

## 6. Interface contract

### 6.1 Daemon modules

| File | Contents |
|------|----------|
| `daemon/services/capture_manager.py` | `CaptureMode.DHCP_GATEWAY = "dhcp_gateway"`; non-abstract `async def reconcile(self) -> None` (default no-op) |
| `daemon/services/capture_config.py` | `CaptureConfig` gains `dhcp_subnet="10.77.0.0/24"`, `dhcp_upstream_address=""`, `dhcp_upstream_gateway=""`, `dhcp_enabled=False`; `[dhcp_gateway]` read/write; `write_env_file` emits `PCAP_FILTER`; atomic writes |
| `daemon/services/dhcp_probe.py` | `build_discover(xid: int, mac: bytes) -> bytes`; `parse_offer(frame: bytes, xid: int) -> dict \| None` (`{"server_ip", "offered_ip"}`); `async probe_dhcp_servers(iface: str, mac: str, timeout: float = 3.0) -> list[dict]` |
| `daemon/services/dhcp_gateway_net.py` | Pure helpers: `validate_subnet`, `gateway_ip`, `pool_range`, `capture_filter`, `firewall_rules(subnet, iface)`, `render_netplan(...)`, `render_sysctl(iface)`, `render_firewall_script(...)`, `render_systemd_unit()`, `parse_leases(text)` |
| `daemon/services/dhcp_gateway.py` | `DhcpGatewayManager(CaptureManager)`: `setup`, `teardown`, `get_health`, `get_capture_interface`, `get_stats`, `mode`, `reconcile`, plus `preflight()`, `enable()`, `disable()`, `status()` |
| `daemon/api/dhcp_gateway.py` | Routes below; `register_dhcp_gateway_routes(app)` called from `server.py` |
| `daemon/api/setup.py` | Accepts `capture_mode: "dhcp_gateway"`; writes INI + `capture.env` to the paths the readers use; restarts capture containers when `capture.env` changes; swaps `app["capture_manager"]` (tearing down an active DHCP gateway first) |
| `daemon/main.py` | DHCP branch at startup (calls `setup()` if routing active). The generic capture loop reads `app["capture_manager"]` each tick and calls `reconcile()` then `get_health()`, and runs in every mode. Storage and SMART tasks start before capture setup, and capture setup is guarded (CR-167) |

### 6.2 HTTP API (daemon; session required. `preflight` and `status` go through the web catch-all proxy; `enable`, `disable` and `/api/setup/configure` have dedicated SvelteKit routes with a 60 s timeout, because enable probes for 3 s, waits for dnsmasq and may restart the capture containers)

All four return `409 {"error": ...}` when the configured mode isn't
`dhcp_gateway`.

**`GET /api/capture/dhcp/preflight`** → 200

```json
{
  "interface": "enp1s0",
  "subnet": "10.77.0.0/24",
  "gateway_ip": "10.77.0.1",
  "upstream": {"address": "192.168.1.50/24", "gateway": "192.168.1.1"},
  "subnet_conflicts": [],
  "other_dhcp_servers": [{"server_ip": "192.168.1.1", "offered_ip": "192.168.1.77"}],
  "ipv6_router_advertisements": true,
  "ip_forward": true,
  "firewall_backend": "iptables-nft",
  "checks": [{"name": "no_other_dhcp", "passed": false, "blocking": true,
              "message": "Your router's DHCP server is still on (192.168.1.1)."}],
  "ready": false
}
```

`upstream` is `null` when the NIC has no router-subnet address or default
route. Check names: `interface_up`, `upstream_detected`, `no_other_dhcp`,
`no_subnet_conflict`, `ip_forward`, `firewall_backend` (all blocking) and
`ipv6_bypass` (non-blocking). `ready` = every blocking check passed.

**`POST /api/capture/dhcp/enable`**, body `{"confirm": true}` → 200 status
body (below). `400` without `confirm: true`. `409 {"error", "checks"}` when a
fresh preflight fails a blocking check. `500 {"error"}` when applying fails
(partial state is rolled back).

**`POST /api/capture/dhcp/disable`** → 200 status body.

**`GET /api/capture/dhcp/status`** → 200

```json
{
  "interface": "enp1s0",
  "subnet": "10.77.0.0/24",
  "gateway_ip": "10.77.0.1",
  "upstream": {"address": "192.168.1.50/24", "gateway": "192.168.1.1"},
  "routing_active": true,
  "dhcp_enabled": true,
  "dhcp_server_running": true,
  "leases": [{"mac": "aa:bb:cc:dd:ee:ff", "ip": "10.77.0.23", "hostname": "pixel-8", "expires": 1793389200}],
  "issues": []
}
```

**`POST /api/setup/configure`** (existing) adds:
`{"capture_mode": "dhcp_gateway", "capture_interface": "enp1s0", "dhcp_subnet": "10.77.0.0/24"}`.
`dhcp_subnet` is optional (defaults to `10.77.0.0/24`) and validated as
private, prefix 16–28. The response adds `"capture_restart": {"restarted": [...], "errors": [...]}`.

`GET /api/capture/health` in DHCP mode: `mode: "dhcp_gateway"`, `status` is
`not_configured` (not enabled yet), `normal`, `degraded` or `down`, plus extra
keys `subnet`, `routing_active`, `dhcp_server_running`, `lease_count`.

### 6.3 Web

| File | Contents |
|------|----------|
| `web/src/lib/api/dhcpGateway.ts` | Types mirroring §6.2; `getDhcpPreflight`, `enableDhcpGateway`, `disableDhcpGateway`, `getDhcpStatus` (throw `Error(message)` on non-OK, with the daemon's `error` text) |
| `web/src/lib/utils/dhcpSubnet.ts` | `validateDhcpSubnet(cidr, nicAddresses) -> { valid: boolean; error: string }` (format, private range, prefix 16–28, not containing any NIC address) |
| `web/src/lib/components/setup/DhcpGatewayStep.svelte` | Wizard step: subnet input (bindable), validation, what happens / limitations in plain English |
| `web/src/routes/setup/+page.svelte` | Mode cards: DHCP gateway (Recommended), Mirror/SPAN. Inline bridge inside an "Advanced" `Collapsible`. DHCP steps: Welcome → Capture Mode → Interfaces (one NIC, "plugged into your router") → DHCP Gateway → Storage → Enrichment → Account → Verification |
| `web/src/lib/components/golive/DhcpGoLive.svelte` | Preflight checks → guided "turn off your router's DHCP" + re-check → confirmation checkbox → Enable → live status (sortable lease table, issues) → Disable + recovery steps |
| `web/src/routes/go-live/+page.svelte` | Reads `/api/capture/mode`. `dhcp_gateway` renders `DhcpGoLive`, anything else the existing bridge flow (bridge polling starts only in bridge mode) |
| `web/src/lib/stores/captureMode.ts` | Store type adds `'dhcp_gateway'` |

## 7. Recovery (shown on the go-live page)

If NetTap is off or broken and devices have no internet:

1. **Turn the router's DHCP server back on.** With NetTap down and the
   router's DHCP off, nothing hands out addresses, so the user first gives a
   laptop a fixed address on the router's network (plugged into the router or
   on its Wi-Fi). When `status.upstream` is known the page fills in real
   values: a free host in the router's network (host .20, skipping NetTap and
   the router), the netmask from the upstream prefix, and the router address,
   e.g. "IP 192.168.1.20, mask 255.255.255.0, then open http://192.168.1.1"
   (`staticAddressHint` in `web/src/lib/utils/dhcpSubnet.ts`). Without
   upstream it says to pick a free address in the router's range and find the
   router's address on its sticker. Routers managed with a phone app (most
   mesh systems) are switched back in the app instead, on mobile data if the
   Wi-Fi has no internet.
2. Reconnect devices (Wi-Fi off/on, or unplug and replug) and they get router
   addresses straight away; otherwise they move over when their NetTap address
   runs out (lease time 1 h). Set the laptop back to automatic addressing.
3. Once NetTap is healthy again, switch the DHCP gateway back on from Go Live.

Timing copy for the switch *to* NetTap: devices move over when their current
address from the router runs out (often up to a day), or straight away if they
reconnect (Wi-Fi off/on or replug). Never promise a fixed number of minutes.

Mode changes: the setup wizard can't save after first run, so no copy sends
users to Setup to switch modes or pick a new subnet. Where a router can't turn
its DHCP off, the page says switching modes after setup isn't available in the
app yet.

## 8. Tests

- **pytest:** probe packet build/parse (fixtures), subnet/pool/filter helpers,
  firewall rule list, renderers (netplan/sysctl/script/unit content, host-path
  symlink), lease parsing, backend detection, enable refusal paths (other DHCP,
  conflict, no upstream, no backend, no confirm), rollback on apply failure,
  reconcile re-adds missing pieces, disable keeps routing, teardown removes
  everything, configure writes INI + `capture.env` at the reader paths,
  container restart only on change, 409 on mode mismatch.
- **vitest:** API client (URLs, methods, errors), subnet validator, wizard
  (DHCP and Mirror primary, bridge under Advanced, DHCP step flow, payload),
  `DhcpGoLive` (loading/error/blocked/ready/enabled states, enable needs the
  confirmation, sortable lease table, disable), go-live mode switch, store.

## 9. Out of scope / follow-ups

- NetTap-side port forwarding (double-NAT workaround).
- In-app host reboot or `netplan apply` (would need a new host privilege path).
- IPv6 routing through NetTap (RA suppression or NAT66).
- DHCP reservations UI; importing the router's existing reservations.
