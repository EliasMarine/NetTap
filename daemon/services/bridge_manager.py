"""
NetTap Bridge Manager Service

Creates and manages the Linux bridge (br0) that sits inline between the ISP
modem and the home/small business router. Network commands run directly in
the host network namespace, which the daemon container shares
(network_mode: host).

Architecture decisions:
    - Host network commands run directly (network_mode: host + NET_ADMIN).
      nsenter was dropped 2026-11-01: Ubuntu's AppArmor profile blocks it.
    - Host filesystem mounts for persistence: writes netplan, systemd unit,
      and sysctl config to mounted host dirs so bridge survives reboot
    - "Soft bypass" via promisc toggle: no Docker socket needed, containers
      stay running but receive no packets when promisc is off
"""

import asyncio
import json
import logging
import os
import re
import textwrap
from pathlib import Path

from services.dhcp_gateway_host import HostNetOps, replace_symlink

logger = logging.getLogger("nettap.services.bridge_manager")

# Host sysfs for reading NIC state (container mounts host /sys at /host/sys)
_SYSFS_NET = os.environ.get("HOST_SYS_NET", "/host/sys/class/net")

# NET-287: NetTap labels every bridge it makes with this alias (ip link set <br> alias nettap)
BRIDGE_ALIAS = "nettap"
NETPLAN_FILE = "10-nettap-bridge.yaml"


def foreign_bridge_message(bridge: str) -> str:
    """Why NetTap won't touch a bridge it didn't make (create, preview, readiness)."""
    return (
        f"This machine already has a network bridge called {bridge} that NetTap didn't set up. "
        "A virtual machine or another network setting may depend on it, so NetTap won't change it. "
        "Use mirror mode, or remove that bridge first. If you're sure NetTap made it, run "
        f"sudo ip link set {bridge} alias {BRIDGE_ALIAS} on this machine and try again. "
        "Nothing was changed."
    )


def foreign_teardown_message(bridge: str) -> str:
    return (
        f"The network bridge {bridge} wasn't set up by NetTap, so NetTap won't remove it. "
        f"If you're sure NetTap made it, run sudo ip link set {bridge} alias {BRIDGE_ALIAS} "
        "on this machine and try again. Nothing was changed."
    )


async def bridge_is_nettaps(bridge_name: str, netplan_dir: str | None = None) -> bool:
    """NET-287: True when NetTap made this bridge, so it may change or remove it.

    Its alias is "nettap" (set at creation), or, for a bridge netplan rebuilt from
    NetTap's file at boot (no alias yet), the legacy evidence holds. ``netplan_dir``
    None means HOST_NETPLAN_DIR.
    """
    bridge_dir = os.path.join(_SYSFS_NET, bridge_name)
    if BridgeManager._read_sysfs(os.path.join(bridge_dir, "ifalias")) == BRIDGE_ALIAS:
        return True
    if netplan_dir is None:
        netplan_dir = os.environ.get("HOST_NETPLAN_DIR", "")
    if not netplan_dir:
        return False  # evidence unavailable; joining '' would read the working dir
    try:
        ports = os.listdir(os.path.join(bridge_dir, "brif"))
        text = Path(netplan_dir, NETPLAN_FILE).read_text()
    except OSError:
        return False
    # Every port must be one NetTap's file lists; an empty bridge proves nothing
    if not ports or not all(
        re.search(rf"^\s*- {re.escape(port)}\s*$", text, re.M) for port in ports
    ):
        return False
    return await _bridge_is_layer2_only(bridge_name)


async def _bridge_is_layer2_only(bridge_name: str) -> bool:
    """No global address and no default route on the bridge, read so a failure refuses.

    NetTap's bridge is pure layer 2; a host uplink bridge carries the host's address.
    """
    host = HostNetOps()
    links = await host.ip_json("addr", "show", "dev", bridge_name)
    if not links or not isinstance(links[0], dict):
        return False  # couldn't read the bridge's addresses
    addrs = links[0].get("addr_info", [])
    if any(isinstance(a, dict) and a.get("scope") == "global" for a in addrs):
        return False
    # Not ip_json: it returns [] for a failed command or bad JSON too
    for family in ("-4", "-6"):
        rc, out, _ = await host._run_nsenter(
            "ip", "-j", family, "route", "show", "default", "dev", bridge_name
        )
        if rc != 0:
            return False
        try:
            # Some iproute2 builds print nothing at all for an empty list
            routes = json.loads(out) if out.strip() else []
        except ValueError:
            return False
        if routes != []:
            return False
    return True


class BridgeManager:
    """Manages bridge creation, teardown, and readiness checks.

    Network commands run in the host network namespace, which the daemon
    container shares (network_mode: host). Persistence files are written to
    mounted host dirs.
    """

    def __init__(
        self,
        bridge_name: str = "br0",
        netplan_dir: str | None = None,
        systemd_dir: str | None = None,
        sysctl_dir: str | None = None,
    ) -> None:
        self._bridge_name = bridge_name
        self._netplan_dir = netplan_dir or os.environ.get("HOST_NETPLAN_DIR", "")
        self._systemd_dir = systemd_dir or os.environ.get("HOST_SYSTEMD_DIR", "")
        self._sysctl_dir = sysctl_dir or os.environ.get("HOST_SYSCTL_DIR", "")

        logger.info(
            "BridgeManager initialized: bridge=%s netplan=%s systemd=%s sysctl=%s",
            bridge_name,
            self._netplan_dir or "(not mounted)",
            self._systemd_dir or "(not mounted)",
            self._sysctl_dir or "(not mounted)",
        )

    # -------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------

    async def create_bridge(
        self,
        wan: str,
        lan: str,
        persist: bool = True,
    ) -> dict:
        """Create and configure the Linux bridge.

        Args:
            wan: WAN-side interface name (e.g., 'enp2s0')
            lan: LAN-side interface name (e.g., 'enp3s0')
            persist: If True, write netplan/systemd/sysctl configs to host

        Returns:
            Dict with created, bridge_name, wan, lan, state, errors,
            warnings, persistence_files.
        """
        errors: list[str] = []
        warnings: list[str] = []
        persistence_files: list[str] = []

        # Validate inputs
        if wan == lan:
            return {
                "created": False,
                "bridge_name": self._bridge_name,
                "wan": wan,
                "lan": lan,
                "state": "error",
                "errors": ["WAN and LAN interfaces must be different"],
                "warnings": [],
                "persistence_files": [],
            }

        # Verify both interfaces exist on the host
        for iface in (wan, lan):
            rc, stdout, _ = await self._run_nsenter("ip", "-j", "link", "show", iface)
            if rc != 0:
                errors.append(f"Interface {iface} does not exist on host")

        if errors:
            return {
                "created": False,
                "bridge_name": self._bridge_name,
                "wan": wan,
                "lan": lan,
                "state": "error",
                "errors": errors,
                "warnings": warnings,
                "persistence_files": [],
            }

        # Check if bridge already exists
        rc, _, _ = await self._run_nsenter("ip", "link", "show", self._bridge_name)
        bridge_existed = rc == 0

        if bridge_existed:
            # NET-287: never adopt a bridge NetTap didn't make
            if not await bridge_is_nettaps(self._bridge_name, self._netplan_dir):
                return self._create_failed(
                    wan, lan, [foreign_bridge_message(self._bridge_name)]
                )
            logger.info("Bridge %s already exists — reconfiguring", self._bridge_name)
            # OLD CODE START — NET-287: ports were released before the bridge was marked as NetTap's
            # # Remove existing member interfaces before re-adding
            # for iface in (wan, lan):
            #     await self._run_nsenter("ip", "link", "set", iface, "nomaster")
            # OLD CODE END
        else:
            # Create bridge
            rc, _, err = await self._run_nsenter(
                "ip", "link", "add", self._bridge_name, "type", "bridge"
            )
            if rc != 0:
                errors.append(f"Failed to create bridge: {err.strip()}")
                return {
                    "created": False,
                    "bridge_name": self._bridge_name,
                    "wan": wan,
                    "lan": lan,
                    "state": "error",
                    "errors": errors,
                    "warnings": warnings,
                    "persistence_files": [],
                }

        # NET-287: label the bridge NetTap's before any port or setting changes
        alias_error = await self._mark_as_nettaps(created=not bridge_existed)
        if alias_error:
            return self._create_failed(wan, lan, [alias_error])

        if bridge_existed:
            # Remove existing member interfaces before re-adding
            for iface in (wan, lan):
                await self._run_nsenter("ip", "link", "set", iface, "nomaster")

        # Tune bridge parameters — STP off, fast forwarding
        bridge_params = [
            ("stp_state", "0"),
            ("forward_delay", "0"),
            ("multicast_snooping", "0"),
            ("ageing_time", "0"),
        ]
        for param, value in bridge_params:
            rc, _, err = await self._run_nsenter(
                "ip", "link", "set", self._bridge_name, "type", "bridge", param, value
            )
            if rc != 0:
                warnings.append(f"Could not set bridge {param}={value}: {err.strip()}")

        # Add interfaces to bridge and enable promiscuous mode
        for iface in (wan, lan):
            rc, _, err = await self._run_nsenter(
                "ip", "link", "set", iface, "master", self._bridge_name
            )
            if rc != 0:
                errors.append(f"Failed to add {iface} to bridge: {err.strip()}")
                continue

            rc, _, err = await self._run_nsenter(
                "ip", "link", "set", iface, "promisc", "on"
            )
            if rc != 0:
                warnings.append(f"Could not enable promisc on {iface}: {err.strip()}")

            # Bring interface UP
            rc, _, err = await self._run_nsenter("ip", "link", "set", iface, "up")
            if rc != 0:
                warnings.append(f"Could not bring {iface} up: {err.strip()}")

        if errors:
            return {
                "created": False,
                "bridge_name": self._bridge_name,
                "wan": wan,
                "lan": lan,
                "state": "error",
                "errors": errors,
                "warnings": warnings,
                "persistence_files": [],
            }

        # Disable netfilter on bridge — prevents Docker iptables from breaking traffic
        sysctl_params = [
            "net.bridge.bridge-nf-call-iptables=0",
            "net.bridge.bridge-nf-call-ip6tables=0",
            "net.bridge.bridge-nf-call-arptables=0",
        ]
        for param in sysctl_params:
            rc, _, err = await self._run_nsenter("sysctl", "-w", param)
            if rc != 0:
                warnings.append(f"Could not set {param}: {err.strip()}")

        # NIC offload tuning — disable TSO/GSO/GRO/LRO for reliable capture
        for iface in (wan, lan):
            rc, _, err = await self._run_nsenter(
                "ethtool",
                "-K",
                iface,
                "tso",
                "off",
                "gso",
                "off",
                "gro",
                "off",
                "lro",
                "off",
            )
            if rc != 0:
                # ethtool failures are non-critical — some NICs don't support all offloads
                warnings.append(f"Could not disable offloads on {iface}: {err.strip()}")

        # Bring bridge UP
        rc, _, err = await self._run_nsenter(
            "ip", "link", "set", self._bridge_name, "up"
        )
        if rc != 0:
            errors.append(f"Failed to bring bridge up: {err.strip()}")
            return {
                "created": False,
                "bridge_name": self._bridge_name,
                "wan": wan,
                "lan": lan,
                "state": "error",
                "errors": errors,
                "warnings": warnings,
                "persistence_files": [],
            }

        # Disable IPv6 on bridge — appliance is a transparent L2 forwarder
        await self._run_nsenter(
            "sysctl", "-w", f"net.ipv6.conf.{self._bridge_name}.disable_ipv6=1"
        )

        # Persist configuration to host filesystem
        # OLD CODE START — #96: write failures were only logged; setup still said created
        # if persist:
        #     persistence_files = self._write_persistence(wan, lan)
        # OLD CODE END
        persist_failures: list[str] = []
        if persist:
            persistence_files = self._write_persistence(wan, lan, persist_failures)

        state = "reconfigured" if bridge_existed else "created"
        logger.info(
            "Bridge %s %s: wan=%s lan=%s persist=%d files",
            self._bridge_name,
            state,
            wan,
            lan,
            len(persistence_files),
        )

        return {
            "created": True,
            "bridge_name": self._bridge_name,
            "wan": wan,
            "lan": lan,
            "state": state,
            "errors": errors,
            # OLD CODE START — #96: persistence write failures weren't in the response
            # "warnings": warnings,
            # OLD CODE END
            "warnings": [*warnings, *persist_failures],
            "persistence_files": persistence_files,
            # #96: false when the bridge won't come back after a reboot as configured
            "persisted": bool(persistence_files) and not persist_failures,
        }

    async def teardown_bridge(self) -> dict:
        """Remove the bridge and release member interfaces.

        Returns:
            Dict with torn_down and errors.
        """
        errors: list[str] = []

        # Check if bridge exists
        rc, _, _ = await self._run_nsenter("ip", "link", "show", self._bridge_name)
        if rc != 0:
            return {
                "torn_down": False,
                "errors": [f"Bridge {self._bridge_name} does not exist"],
            }

        # NET-287: never remove a bridge NetTap didn't make, nor release its ports
        if not await bridge_is_nettaps(self._bridge_name, self._netplan_dir):
            return {
                "torn_down": False,
                "errors": [foreign_teardown_message(self._bridge_name)],
            }

        # Get member interfaces before teardown
        rc, stdout, _ = await self._run_nsenter(
            "ip", "-j", "link", "show", "master", self._bridge_name
        )
        member_ifaces: list[str] = []
        if rc == 0 and stdout.strip():
            try:
                import json

                links = json.loads(stdout)
                member_ifaces = [
                    link.get("ifname", "") for link in links if link.get("ifname")
                ]
            except (ValueError, KeyError):
                pass

        # Remove members and disable promisc
        for iface in member_ifaces:
            await self._run_nsenter("ip", "link", "set", iface, "nomaster")
            await self._run_nsenter("ip", "link", "set", iface, "promisc", "off")

        # Delete bridge
        rc, _, err = await self._run_nsenter("ip", "link", "del", self._bridge_name)
        if rc != 0:
            errors.append(f"Failed to delete bridge: {err.strip()}")

        logger.info("Bridge %s torn down", self._bridge_name)
        return {
            "torn_down": rc == 0,
            "errors": errors,
        }

    async def check_readiness(self) -> dict:
        """Run readiness checks for bridge deployment.

        Eight checks:
        1. Bridge interface exists
        2. Bridge is UP
        3. WAN NIC has carrier
        4. LAN NIC has carrier
        5. WAN NIC in promiscuous mode
        6. LAN NIC in promiscuous mode
        7. STP is disabled
        8. Netfilter disabled on bridge

        Returns:
            Dict with ready, checks[], and human-readable message.
        """
        checks: list[dict] = []

        # 1. Bridge exists
        bridge_dir = os.path.join(_SYSFS_NET, self._bridge_name)
        bridge_exists = os.path.exists(bridge_dir)
        # NET-287: a bridge NetTap didn't make isn't NetTap's bridge (Go Live showed it as live)
        foreign = bridge_exists and not await bridge_is_nettaps(
            self._bridge_name, self._netplan_dir
        )
        # OLD CODE START — NET-287: any bridge with this name passed
        # checks.append(
        #     {
        #         "name": "bridge_exists",
        #         "passed": bridge_exists,
        #         "detail": f"Bridge {self._bridge_name} {'found' if bridge_exists else 'not found'} in sysfs",
        #     }
        # )
        #
        # if not bridge_exists:
        # OLD CODE END
        checks.append(
            {
                "name": "bridge_exists",
                "passed": bridge_exists and not foreign,
                "detail": foreign_bridge_message(self._bridge_name)
                if foreign
                else f"Bridge {self._bridge_name} {'found' if bridge_exists else 'not found'} in sysfs",
            }
        )

        if foreign:
            for name in (
                "bridge_up",
                "wan_carrier",
                "lan_carrier",
                "wan_promisc",
                "lan_promisc",
                "stp_disabled",
                "netfilter_disabled",
            ):
                checks.append(
                    {
                        "name": name,
                        "passed": False,
                        "detail": "NetTap's bridge does not exist",
                    }
                )
            return {
                "ready": False,
                "checks": checks,
                "message": foreign_bridge_message(self._bridge_name),
            }

        if not bridge_exists:
            # All remaining checks are N/A without a bridge
            for name, detail in [
                ("bridge_up", "Bridge does not exist"),
                ("wan_carrier", "Bridge does not exist"),
                ("lan_carrier", "Bridge does not exist"),
                ("wan_promisc", "Bridge does not exist"),
                ("lan_promisc", "Bridge does not exist"),
                ("stp_disabled", "Bridge does not exist"),
                ("netfilter_disabled", "Bridge does not exist"),
            ]:
                checks.append({"name": name, "passed": False, "detail": detail})

            return {
                "ready": False,
                "checks": checks,
                "message": "Bridge has not been configured yet. Run the setup wizard or create the bridge from the Go Live page.",
            }

        # 2. Bridge is UP
        bridge_up = self._read_sysfs(os.path.join(bridge_dir, "operstate")) == "up"
        checks.append(
            {
                "name": "bridge_up",
                "passed": bridge_up,
                "detail": f"Bridge {self._bridge_name} is {'UP' if bridge_up else 'DOWN'}",
            }
        )

        # Discover member interfaces from bridge
        wan_iface, lan_iface = await self._discover_members()

        # 3. WAN carrier
        wan_carrier = (
            self._read_sysfs(os.path.join(_SYSFS_NET, wan_iface, "carrier")) == "1"
            if wan_iface
            else False
        )
        checks.append(
            {
                "name": "wan_carrier",
                "passed": wan_carrier,
                "detail": f"WAN ({wan_iface or 'unknown'}) carrier {'detected' if wan_carrier else 'not detected — connect cable to WAN port'}",
            }
        )

        # 4. LAN carrier
        lan_carrier = (
            self._read_sysfs(os.path.join(_SYSFS_NET, lan_iface, "carrier")) == "1"
            if lan_iface
            else False
        )
        checks.append(
            {
                "name": "lan_carrier",
                "passed": lan_carrier,
                "detail": f"LAN ({lan_iface or 'unknown'}) carrier {'detected' if lan_carrier else 'not detected — connect cable to LAN port'}",
            }
        )

        # 5. WAN promisc
        wan_promisc = await self._check_promisc(wan_iface) if wan_iface else False
        checks.append(
            {
                "name": "wan_promisc",
                "passed": wan_promisc,
                "detail": f"WAN ({wan_iface or 'unknown'}) promiscuous mode {'enabled' if wan_promisc else 'disabled'}",
            }
        )

        # 6. LAN promisc
        lan_promisc = await self._check_promisc(lan_iface) if lan_iface else False
        checks.append(
            {
                "name": "lan_promisc",
                "passed": lan_promisc,
                "detail": f"LAN ({lan_iface or 'unknown'}) promiscuous mode {'enabled' if lan_promisc else 'disabled'}",
            }
        )

        # 7. STP disabled
        stp_val = self._read_sysfs(os.path.join(bridge_dir, "bridge", "stp_state"))
        stp_disabled = stp_val == "0"
        checks.append(
            {
                "name": "stp_disabled",
                "passed": stp_disabled,
                "detail": f"STP {'disabled' if stp_disabled else 'enabled (should be disabled for inline tap)'}",
            }
        )

        # 8. Netfilter disabled — read from the HOST network namespace. The
        # daemon shares it (network_mode: host); a container with its own
        # namespace would read its own value (always 1), not the host's.
        # If the file doesn't exist, the br_netfilter kernel module is not
        # loaded — meaning bridge traffic is NOT subject to iptables at all,
        # which is the desired state (effectively disabled).
        rc, nf_out, _ = await self._run_nsenter(
            "cat", "/proc/sys/net/bridge/bridge-nf-call-iptables"
        )
        if rc == 0:
            nf_disabled = nf_out.strip() == "0"
            nf_detail = f"Bridge netfilter {'disabled' if nf_disabled else 'enabled (Docker iptables may break traffic)'}"
        else:
            # File doesn't exist → br_netfilter module not loaded → no interference
            nf_disabled = True
            nf_detail = "Bridge netfilter not loaded (br_netfilter module absent — no iptables interference)"
        checks.append(
            {
                "name": "netfilter_disabled",
                "passed": nf_disabled,
                "detail": nf_detail,
            }
        )

        # Determine overall readiness and message
        all_passed = all(c["passed"] for c in checks)
        failed = [c for c in checks if not c["passed"]]

        if all_passed:
            message = "All checks passed. Your network is ready for monitoring."
        elif not bridge_up:
            message = "Bridge exists but is DOWN. It may need to be brought up."
        elif not wan_carrier and not lan_carrier:
            message = "Bridge is UP but no cables are connected. Follow the wiring guide to connect your ISP modem and router."
        elif not wan_carrier:
            message = "Waiting for WAN cable. Connect the cable from your ISP modem to the WAN port."
        elif not lan_carrier:
            message = "Waiting for LAN cable. Connect the cable from the LAN port to your router."
        else:
            # Some non-carrier checks failed
            detail_list = "; ".join(c["detail"] for c in failed)
            message = (
                f"Bridge is operational but some checks need attention: {detail_list}"
            )

        return {
            "ready": all_passed,
            "checks": checks,
            "message": message,
        }

    # -------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------

    async def _mark_as_nettaps(self, created: bool) -> str | None:
        """Set the bridge's "nettap" alias (NET-287); the error, or None when set.

        Runs before any port or setting changes. On failure a bridge this call
        created (still empty) is deleted again, so nothing is left changed.
        """
        rc, _, err = await self._run_nsenter(
            "ip", "link", "set", self._bridge_name, "alias", BRIDGE_ALIAS
        )
        if rc == 0:
            return None
        if created:
            await self._run_nsenter("ip", "link", "del", self._bridge_name)
        return (
            f"Could not mark {self._bridge_name} as NetTap's bridge: "
            f"{err.strip() or f'exit code {rc}'}. Nothing was changed."
        )

    def _create_failed(self, wan: str, lan: str, errors: list[str]) -> dict:
        return {
            "created": False,
            "bridge_name": self._bridge_name,
            "wan": wan,
            "lan": lan,
            "state": "error",
            "errors": errors,
            "warnings": [],
            "persistence_files": [],
        }

    async def _run_nsenter(self, *args: str) -> tuple[int, str, str]:
        """Run a command in the host network namespace (network_mode: host).

        Returns:
            Tuple of (returncode, stdout, stderr).
        """
        # OLD CODE START — replaced 2026-11-01: Ubuntu's docker-default AppArmor
        # profile denies nsenter's ptrace read of PID 1, so every host command
        # failed. The daemon runs with network_mode: host, so run them directly.
        # cmd = ["nsenter", "-t", "1", "-n", "--"] + list(args)
        # OLD CODE END
        cmd = list(args)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            return (
                proc.returncode or 0,
                stdout.decode("utf-8", errors="replace"),
                stderr.decode("utf-8", errors="replace"),
            )
        except asyncio.TimeoutError:
            logger.warning("Host command timed out: %s", " ".join(cmd))
            return (1, "", "timeout")
        except FileNotFoundError:
            logger.debug("%s not available", cmd[0])
            return (1, "", f"{cmd[0]} not found")

    async def _discover_members(self) -> tuple[str, str]:
        """Discover WAN and LAN member interfaces of the bridge.

        Reads the bridge's brif directory from sysfs to find member interfaces.
        Returns the first two members as (wan, lan). Falls back to environment
        variables WAN_IFACE/LAN_IFACE if sysfs discovery fails.

        Returns:
            Tuple of (wan_iface, lan_iface).
        """
        brif_dir = os.path.join(_SYSFS_NET, self._bridge_name, "brif")
        members: list[str] = []
        try:
            if os.path.isdir(brif_dir):
                members = sorted(os.listdir(brif_dir))
        except OSError:
            pass

        if len(members) >= 2:
            return (members[0], members[1])

        # Fall back to env vars
        wan = os.environ.get("WAN_IFACE", "eth0")
        lan = os.environ.get("LAN_IFACE", "eth1")
        return (wan, lan)

    async def _check_promisc(self, iface: str) -> bool:
        """Check if an interface has promiscuous mode enabled.

        Reads the interface flags from sysfs and checks for IFF_PROMISC (0x100).
        """
        flags_str = self._read_sysfs(os.path.join(_SYSFS_NET, iface, "flags"))
        if not flags_str:
            return False
        try:
            flags = int(flags_str, 16)
            return bool(flags & 0x100)  # IFF_PROMISC
        except ValueError:
            return False

    def _write_persistence(
        self, wan: str, lan: str, failures: list[str] | None = None
    ) -> list[str]:
        """Write bridge persistence files to mounted host directories.

        Writes:
        1. Netplan YAML for bridge configuration
        2. Systemd unit for bridge bring-up at boot
        3. Sysctl config for bridge netfilter disable

        Each write that fails is appended to ``failures`` when given (#96).

        Returns:
            List of file paths written.
        """
        files_written: list[str] = []
        failures = [] if failures is None else failures

        # 1. Netplan YAML
        if self._netplan_dir:
            netplan_path = os.path.join(self._netplan_dir, "10-nettap-bridge.yaml")
            netplan_content = textwrap.dedent(f"""\
                # NetTap bridge configuration — auto-generated
                # Do not edit manually; regenerated by NetTap setup wizard
                network:
                  version: 2
                  renderer: networkd
                  ethernets:
                    {wan}:
                      dhcp4: false
                      dhcp6: false
                    {lan}:
                      dhcp4: false
                      dhcp6: false
                  bridges:
                    {self._bridge_name}:
                      interfaces:
                        - {wan}
                        - {lan}
                      dhcp4: false
                      dhcp6: false
                      parameters:
                        stp: false
                        forward-delay: 0
            """)
            try:
                Path(netplan_path).write_text(netplan_content)
                files_written.append(netplan_path)
                logger.info("Wrote netplan config: %s", netplan_path)
            except OSError as exc:
                logger.warning("Could not write netplan config: %s", exc)
                failures.append(f"Could not write netplan config {netplan_path}: {exc}")

        # 2. Systemd unit
        if self._systemd_dir:
            unit_path = os.path.join(self._systemd_dir, "nettap-bridge.service")
            unit_content = textwrap.dedent(f"""\
                # NetTap bridge service — auto-generated
                # Ensures bridge is UP at boot before capture containers start
                [Unit]
                Description=NetTap Bridge Setup
                After=network-online.target systemd-networkd-wait-online.service
                Wants=network-online.target
                Before=docker.service

                [Service]
                Type=oneshot
                RemainAfterExit=yes
                ExecStart=/sbin/ip link set {self._bridge_name} up
                ExecStart=/sbin/ip link set {wan} promisc on
                ExecStart=/sbin/ip link set {lan} promisc on
                ExecStart=/sbin/sysctl -w net.bridge.bridge-nf-call-iptables=0
                ExecStart=/sbin/sysctl -w net.bridge.bridge-nf-call-ip6tables=0
                ExecStart=/sbin/sysctl -w net.bridge.bridge-nf-call-arptables=0

                [Install]
                WantedBy=multi-user.target
            """)
            try:
                Path(unit_path).write_text(unit_content)
                files_written.append(unit_path)
                logger.info("Wrote systemd unit: %s", unit_path)

                # Create symlink in multi-user.target.wants/ if dir exists
                wants_dir = os.path.join(self._systemd_dir, "multi-user.target.wants")
                if os.path.isdir(wants_dir):
                    symlink_path = os.path.join(wants_dir, "nettap-bridge.service")
                    try:
                        # OLD CODE START — replaced 2026-10-30 (LD-001): the target was
                        # the container path (/host/etc/...), which doesn't exist on the
                        # host, so systemd never started the unit; exists() is also False
                        # for that dangling link, so re-creating it hit FileExistsError.
                        # if os.path.exists(symlink_path):
                        #     os.remove(symlink_path)
                        # os.symlink(unit_path, symlink_path)
                        # OLD CODE END
                        # Relative target resolves on the host and in the container
                        replace_symlink(
                            os.path.join("..", os.path.basename(unit_path)),
                            symlink_path,
                        )
                        logger.info("Created systemd symlink: %s", symlink_path)
                    except OSError as exc:
                        logger.warning("Could not create systemd symlink: %s", exc)
                        failures.append(
                            f"Could not enable nettap-bridge.service at boot: {exc}"
                        )
            except OSError as exc:
                logger.warning("Could not write systemd unit: %s", exc)
                failures.append(f"Could not write systemd unit {unit_path}: {exc}")

        # 3. Sysctl config
        if self._sysctl_dir:
            sysctl_path = os.path.join(self._sysctl_dir, "99-nettap-bridge.conf")
            sysctl_content = textwrap.dedent("""\
                # NetTap bridge netfilter disable — auto-generated
                # Prevents Docker iptables from interfering with bridged traffic
                net.bridge.bridge-nf-call-iptables = 0
                net.bridge.bridge-nf-call-ip6tables = 0
                net.bridge.bridge-nf-call-arptables = 0
            """)
            try:
                Path(sysctl_path).write_text(sysctl_content)
                files_written.append(sysctl_path)
                logger.info("Wrote sysctl config: %s", sysctl_path)
            except OSError as exc:
                logger.warning("Could not write sysctl config: %s", exc)
                failures.append(f"Could not write sysctl config {sysctl_path}: {exc}")

        return files_written

    @staticmethod
    def _read_sysfs(path: str) -> str:
        """Read a sysfs/proc file and return its contents. Empty string on error."""
        try:
            with open(path, "r") as f:
                return f.read().strip()
        except (FileNotFoundError, PermissionError, OSError):
            return ""
