"""
NetTap Mirror Manager Service

Manages a mirror/SPAN capture interface for passive network monitoring.
Unlike bridge mode (inline between modem and router), mirror mode listens
on a single NIC that receives mirrored traffic from a managed switch.

The mirror NIC:
    - Has NO IP address (pure capture-only)
    - Runs in promiscuous mode
    - Has all offloads disabled (TSO, GSO, GRO, LRO, rx-vlan-offload)
    - Has ring buffer maximized
    - Is NOT part of a bridge

Architecture decisions:
    - Host network commands run directly: the daemon container uses
      network_mode: host and NET_ADMIN. (nsenter was dropped 2026-11-01 because
      Ubuntu's docker-default AppArmor profile blocks it.)
    - Host filesystem mounts for persistence: writes networkd and systemd configs
      to mounted host dirs so mirror NIC config survives reboot
    - Separate management interface: web UI access uses a different NIC so the
      mirror NIC can be fully dedicated to capture
"""

import asyncio
import logging
import os
import textwrap
from pathlib import Path

from .capture_manager import (
    CaptureHealth,
    CaptureManager,
    CaptureMode,
    CaptureStats,
)
from .dhcp_gateway_host import replace_symlink

logger = logging.getLogger("nettap.services.mirror_manager")

# Host sysfs for reading NIC state (container mounts host /sys at /host/sys)
_SYSFS_NET = os.environ.get("HOST_SYS_NET", "/host/sys/class/net")


class MirrorManager(CaptureManager):
    """Manages a mirror/SPAN capture interface.

    Network commands run in the host network namespace, which the daemon
    container shares (network_mode: host). Persistence files are written to
    mounted host dirs.
    """

    def __init__(
        self,
        interface: str,
        management_interface: str = "",
        netplan_dir: str | None = None,
        systemd_dir: str | None = None,
    ) -> None:
        self._interface = interface
        self._management_interface = management_interface or os.environ.get(
            "MGMT_IFACE", ""
        )
        self._netplan_dir = netplan_dir or os.environ.get("HOST_NETPLAN_DIR", "")
        self._systemd_dir = systemd_dir or os.environ.get("HOST_SYSTEMD_DIR", "")

        logger.info(
            "MirrorManager initialized: interface=%s mgmt=%s netplan=%s systemd=%s",
            interface,
            self._management_interface or "(not set)",
            self._netplan_dir or "(not mounted)",
            self._systemd_dir or "(not mounted)",
        )

    # -------------------------------------------------------------------
    # CaptureManager interface
    # -------------------------------------------------------------------

    async def setup(self) -> dict:
        """Configure the mirror capture interface.

        Steps:
            1. Verify interface exists on the host
            2. Strip any IP address
            3. Write networkd config to prevent DHCP
            4. Enable promiscuous mode
            5. Disable NIC offloads (TSO, GSO, GRO, LRO, rx-vlan-offload)
            6. Maximize ring buffer
            7. Bring interface UP
            8. Disable IPv6
            9. Write systemd persistence unit

        Returns:
            Dict with success, warnings, errors, and persistence_files.
        """
        errors: list[str] = []
        warnings: list[str] = []
        persistence_files: list[str] = []

        # Verify interface exists on the host
        rc, _, err = await self._run_nsenter(
            "ip", "-j", "link", "show", self._interface
        )
        if rc != 0:
            errors.append(
                f"Interface {self._interface} does not exist on host: {err.strip()}"
            )
            return {
                "success": False,
                "interface": self._interface,
                "errors": errors,
                "warnings": warnings,
                "persistence_files": [],
            }

        # 1. Strip any IP address from the mirror interface
        rc, _, err = await self._run_nsenter(
            "ip", "addr", "flush", "dev", self._interface
        )
        if rc != 0:
            warnings.append(f"Could not flush IP addresses: {err.strip()}")

        # 2. Write networkd config to prevent DHCP on mirror interface
        if self._netplan_dir:
            networkd_files = self._write_networkd_config()
            persistence_files.extend(networkd_files)

        # 3. Enable promiscuous mode
        rc, _, err = await self._run_nsenter(
            "ip", "link", "set", self._interface, "promisc", "on"
        )
        if rc != 0:
            errors.append(f"Failed to enable promiscuous mode: {err.strip()}")

        # 4. Disable NIC offloads — prevents reassembly that hides real packet sizes
        rc, _, err = await self._run_nsenter(
            "ethtool",
            "-K",
            self._interface,
            "tso",
            "off",
            "gso",
            "off",
            "gro",
            "off",
            "lro",
            "off",
            "rx-vlan-offload",
            "off",
        )
        if rc != 0:
            # ethtool failures are non-critical — some NICs don't support all offloads
            warnings.append(
                f"Could not disable all offloads on {self._interface}: {err.strip()}"
            )

        # 5. Maximize ring buffer for reduced packet drops under load
        rc, _, err = await self._run_nsenter(
            "ethtool", "-G", self._interface, "rx", "4096"
        )
        if rc != 0:
            # Non-critical — NIC may not support ring buffer tuning or max may be lower
            warnings.append(
                f"Could not set ring buffer to 4096 on {self._interface}: {err.strip()}"
            )

        # 6. Bring interface UP
        rc, _, err = await self._run_nsenter("ip", "link", "set", self._interface, "up")
        if rc != 0:
            errors.append(f"Failed to bring {self._interface} up: {err.strip()}")

        # 7. Disable IPv6 — mirror NIC should not participate in any L3
        rc, _, err = await self._run_nsenter(
            "sysctl", "-w", f"net.ipv6.conf.{self._interface}.disable_ipv6=1"
        )
        if rc != 0:
            warnings.append(
                f"Could not disable IPv6 on {self._interface}: {err.strip()}"
            )

        # 8. Write systemd persistence unit
        if self._systemd_dir:
            systemd_files = self._write_systemd_persistence()
            persistence_files.extend(systemd_files)

        success = len(errors) == 0
        if success:
            logger.info(
                "Mirror interface %s configured: promisc=on offloads=off "
                "ring_buffer=4096 ipv6=off persist=%d files",
                self._interface,
                len(persistence_files),
            )
        else:
            logger.error(
                "Mirror interface %s setup failed: errors=%s",
                self._interface,
                errors,
            )

        return {
            "success": success,
            "interface": self._interface,
            "errors": errors,
            "warnings": warnings,
            "persistence_files": persistence_files,
        }

    async def teardown(self) -> dict:
        """Deconfigure the mirror capture interface.

        Disables promiscuous mode on the mirror NIC. Does not remove
        persistence files (they are idempotent and harmless).

        Returns:
            Dict with torn_down and errors.
        """
        errors: list[str] = []

        # Disable promiscuous mode
        rc, _, err = await self._run_nsenter(
            "ip", "link", "set", self._interface, "promisc", "off"
        )
        if rc != 0:
            errors.append(
                f"Failed to disable promiscuous mode on {self._interface}: {err.strip()}"
            )

        if not errors:
            logger.info(
                "Mirror interface %s torn down (promisc disabled)", self._interface
            )
        else:
            logger.warning(
                "Mirror interface %s teardown had errors: %s", self._interface, errors
            )

        return {
            "torn_down": len(errors) == 0,
            "interface": self._interface,
            "errors": errors,
        }

    async def get_health(self) -> CaptureHealth:
        """Get current mirror capture health status.

        Checks:
            1. Interface exists in sysfs
            2. Operational state is "up"
            3. Carrier (link) detected
            4. Promiscuous mode enabled (flags & 0x100)
            5. No IP address assigned

        Returns:
            CaptureHealth with mode="mirror" and appropriate status.
        """
        issues: list[str] = []
        iface_dir = os.path.join(_SYSFS_NET, self._interface)

        # Check 1: Interface exists
        if not os.path.exists(iface_dir):
            return CaptureHealth(
                mode=CaptureMode.MIRROR.value,
                status="not_configured",
                capture_interface=self._interface,
                link_up=False,
                promisc_enabled=False,
                issues=[f"Interface {self._interface} not found in sysfs"],
                extra={"management_interface": self._management_interface},
            )

        # Check 2: Operational state
        operstate = self._read_sysfs_file(os.path.join(iface_dir, "operstate"))
        link_up = operstate == "up"
        if not link_up:
            issues.append(
                f"Interface {self._interface} is {operstate or 'unknown'} (expected up)"
            )

        # Check 3: Carrier detected
        carrier = self._read_sysfs_file(os.path.join(iface_dir, "carrier"))
        carrier_up = carrier == "1"
        if not carrier_up:
            issues.append(
                f"No carrier on {self._interface} — check cable from switch mirror port"
            )

        # Check 4: Promiscuous mode
        promisc_enabled = self._check_promisc()
        if not promisc_enabled:
            issues.append(f"Promiscuous mode not enabled on {self._interface}")

        # Check 5: No IP address (mirror NIC should be capture-only)
        has_ip = await self._check_has_ip()
        if has_ip:
            issues.append(
                f"IP address assigned to {self._interface} — mirror NIC "
                f"should have no IP (capture-only)"
            )
        elif has_ip is None:
            issues.append(
                f"Could not check whether {self._interface} has an IP address"
            )

        # Determine overall status
        if not link_up and not carrier_up:
            status = "down"
        elif issues:
            status = "degraded"
        else:
            status = "normal"

        return CaptureHealth(
            mode=CaptureMode.MIRROR.value,
            status=status,
            capture_interface=self._interface,
            link_up=link_up and carrier_up,
            promisc_enabled=promisc_enabled,
            issues=issues,
            extra={
                "management_interface": self._management_interface,
                "carrier": carrier_up,
                "has_ip": has_ip,
            },
        )

    def get_capture_interface(self) -> str:
        """Get the mirror interface name for capture tools.

        Returns:
            The mirror NIC name (e.g., 'enp2s0').
        """
        return self._interface

    async def get_stats(self) -> CaptureStats:
        """Get mirror interface statistics from sysfs.

        Reads rx/tx byte and packet counters, drop counters, missed errors,
        and link speed. Calculates drop rate percentage.

        Returns:
            CaptureStats with interface metrics.
        """
        stats_dir = os.path.join(_SYSFS_NET, self._interface, "statistics")

        # Read counters from sysfs
        rx_bytes = self._read_sysfs_int(os.path.join(stats_dir, "rx_bytes"))
        tx_bytes = self._read_sysfs_int(os.path.join(stats_dir, "tx_bytes"))
        rx_packets = self._read_sysfs_int(os.path.join(stats_dir, "rx_packets"))
        tx_packets = self._read_sysfs_int(os.path.join(stats_dir, "tx_packets"))
        rx_dropped = self._read_sysfs_int(os.path.join(stats_dir, "rx_dropped"))
        rx_missed_errors = self._read_sysfs_int(
            os.path.join(stats_dir, "rx_missed_errors")
        )

        # Read link speed (in Mbps)
        speed_str = self._read_sysfs_file(
            os.path.join(_SYSFS_NET, self._interface, "speed")
        )
        try:
            link_speed_mbps = int(speed_str) if speed_str else 0
            # Kernel returns -1 or very large values when speed is unknown
            if link_speed_mbps < 0 or link_speed_mbps > 400000:
                link_speed_mbps = 0
        except ValueError:
            link_speed_mbps = 0

        # Calculate drop rate
        total_rx = rx_packets + rx_dropped
        drop_rate_pct = round((rx_dropped / total_rx) * 100, 4) if total_rx > 0 else 0.0

        return CaptureStats(
            capture_interface=self._interface,
            rx_bytes=rx_bytes,
            tx_bytes=tx_bytes,
            rx_packets=rx_packets,
            tx_packets=tx_packets,
            rx_dropped=rx_dropped,
            rx_missed_errors=rx_missed_errors,
            link_speed_mbps=link_speed_mbps,
            drop_rate_pct=drop_rate_pct,
        )

    @property
    def mode(self) -> CaptureMode:
        """The capture mode this manager implements."""
        return CaptureMode.MIRROR

    # -------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------

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

    def _check_promisc(self) -> bool:
        """Check if the mirror interface has promiscuous mode enabled.

        Reads the interface flags from sysfs and checks for IFF_PROMISC (0x100).
        """
        flags_str = self._read_sysfs_file(
            os.path.join(_SYSFS_NET, self._interface, "flags")
        )
        if not flags_str:
            return False
        try:
            flags = int(flags_str, 16)
            return bool(flags & 0x100)  # IFF_PROMISC
        except ValueError:
            return False

    async def _check_has_ip(self) -> bool | None:
        """Check if the mirror interface has any IP address assigned.

        Mirror NICs should be capture-only with no L3 configuration.

        Returns:
            True if any IP address is assigned, False if none, None if
            ``ip`` failed or its output couldn't be read (not checked).
        """
        rc, stdout, _ = await self._run_nsenter(
            "ip", "-j", "addr", "show", "dev", self._interface
        )
        # OLD CODE START — #96: a failed check read as "no IP", so health could say normal
        # if rc != 0:
        #     return False
        # OLD CODE END
        if rc != 0:
            return None

        try:
            import json

            iface_data = json.loads(stdout)
            if iface_data and isinstance(iface_data, list):
                addr_info = iface_data[0].get("addr_info", [])
                # Filter out link-local (fe80::) — only flag routable addresses
                for addr in addr_info:
                    family = addr.get("family", "")
                    local = addr.get("local", "")
                    if family == "inet":
                        return True
                    if family == "inet6" and not local.startswith("fe80"):
                        return True
            return False
        # OLD CODE START — #96: unreadable output read as "no IP"
        # except (ValueError, KeyError, IndexError):
        #     return False
        # OLD CODE END
        except (ValueError, KeyError, IndexError, AttributeError):
            return None

    def _write_networkd_config(self) -> list[str]:
        """Write systemd-networkd config to prevent DHCP on the mirror NIC.

        Creates a netplan YAML that matches the mirror interface and
        explicitly disables DHCP and link-local addressing.

        Returns:
            List of file paths written.
        """
        files_written: list[str] = []

        netplan_path = os.path.join(
            self._netplan_dir, f"10-nettap-mirror-{self._interface}.yaml"
        )
        netplan_content = textwrap.dedent(f"""\
            # NetTap mirror interface configuration — auto-generated
            # Prevents DHCP/IPv6 on the mirror capture NIC
            # Do not edit manually; regenerated by NetTap setup
            network:
              version: 2
              renderer: networkd
              ethernets:
                {self._interface}:
                  dhcp4: false
                  dhcp6: false
                  link-local: []
                  optional: true
        """)
        try:
            Path(netplan_path).write_text(netplan_content)
            files_written.append(netplan_path)
            logger.info("Wrote networkd config: %s", netplan_path)
        except OSError as exc:
            logger.warning("Could not write networkd config: %s", exc)

        return files_written

    def _write_systemd_persistence(self) -> list[str]:
        """Write a systemd unit for mirror NIC setup on boot.

        Ensures the mirror NIC comes up in promiscuous mode with no IP,
        offloads disabled, and ring buffer maximized at every boot —
        before Docker and capture containers start.

        Returns:
            List of file paths written.
        """
        files_written: list[str] = []

        unit_path = os.path.join(self._systemd_dir, "nettap-mirror.service")
        # OLD CODE START — removed 2026-11-01 (CR-076): the unit ran, at every boot
        # and by NIC name with no in-use check,
        #   ExecStart=/sbin/ip addr flush dev {self._interface}
        # After a NIC rename that strips the management port. The netplan file
        # (dhcp4/dhcp6 false, link-local: []) already keeps the NIC address-free.
        # ethtool -K also gained "-": a refused offload (Realtek) stopped the unit
        # before the IPv6 line ran.
        # OLD CODE END
        unit_content = textwrap.dedent(f"""\
            # NetTap mirror interface service — auto-generated
            # Configures mirror/SPAN capture NIC at boot
            [Unit]
            Description=NetTap Mirror Interface Setup ({self._interface})
            After=network-online.target systemd-networkd-wait-online.service
            Wants=network-online.target
            Before=docker.service

            [Service]
            Type=oneshot
            RemainAfterExit=yes
            # Enable promiscuous mode for packet capture
            ExecStart=/sbin/ip link set {self._interface} promisc on
            # Bring interface UP
            ExecStart=/sbin/ip link set {self._interface} up
            # Disable NIC offloads for accurate capture (non-fatal, like the ring buffer)
            ExecStart=-/usr/sbin/ethtool -K {self._interface} tso off gso off gro off lro off rx-vlan-offload off
            # Maximize ring buffer to reduce drops
            ExecStart=-/usr/sbin/ethtool -G {self._interface} rx 4096
            # Disable IPv6
            ExecStart=/sbin/sysctl -w net.ipv6.conf.{self._interface}.disable_ipv6=1

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
                symlink_path = os.path.join(wants_dir, "nettap-mirror.service")
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
                        os.path.join("..", os.path.basename(unit_path)), symlink_path
                    )
                    logger.info("Created systemd symlink: %s", symlink_path)
                except OSError as exc:
                    logger.warning("Could not create systemd symlink: %s", exc)
        except OSError as exc:
            logger.warning("Could not write systemd unit: %s", exc)

        return files_written

    @staticmethod
    def _read_sysfs_file(path: str) -> str:
        """Read a sysfs/proc file and return its contents. Empty string on error."""
        try:
            with open(path, "r") as f:
                return f.read().strip()
        except (FileNotFoundError, PermissionError, OSError):
            return ""

    @staticmethod
    def _read_sysfs_int(path: str) -> int:
        """Read a sysfs file containing an integer value. Returns 0 on error."""
        try:
            with open(path, "r") as f:
                return int(f.read().strip())
        except (FileNotFoundError, PermissionError, OSError, ValueError):
            return 0
