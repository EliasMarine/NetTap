"""
NetTap DHCP Gateway Manager

DHCP gateway capture mode: NetTap serves its own subnet (default
10.77.0.0/24) from dnsmasq, names itself as the gateway, and masquerades
traffic on to the real router. Capture then sees every flow with the device's
real IP and MAC, before the router's NAT. One NIC carries both legs.

State (see docs/plans/2026-10-30-dhcp-gateway-mode-design.md §5):
    - Routing active  <=> mode == dhcp_gateway and an upstream gateway is recorded
    - DHCP running    <=> routing active and dhcp_enabled
    ``disable`` turns off only the DHCP server; ``teardown`` removes everything.

Architecture decisions:
    - Host network commands go through ``nsenter -t 1 -n`` like the bridge
      and mirror managers. dnsmasq and the DHCP probe run in the daemon
      process, which already shares the host network namespace.
    - Firewall rules live in Docker's DOCKER-USER chain (Docker's FORWARD
      policy is DROP) on whichever iptables backend has that chain.
    - Boot persistence does not depend on the daemon: netplan, sysctl, a
      firewall script and a oneshot unit restore routing on their own.

Module layout: pure helpers in dhcp_gateway_net, host commands and dnsmasq
in dhcp_gateway_host, checks in dhcp_gateway_preflight, and reconcile / health
in dhcp_gateway_runtime. This module holds the enable / disable / teardown flow.
"""

import asyncio
import inspect
import ipaddress
import logging
import os
from dataclasses import replace

from services.capture_config import (
    CaptureConfig,
    load_capture_config,
    save_capture_config,
    write_file_atomic,
)
from services.capture_manager import CaptureManager, CaptureMode, CaptureStats
from services.dhcp_gateway_host import (
    DnsmasqProcess,
    HostNetOps,
    read_iface_stats,
    remove_path,
    replace_symlink,
)
from services.dhcp_gateway_net import (
    HOST_UNIT_PATH,
    WANTS_LINK,
    BootDirs,
    boot_files,
    boot_paths,
    dnsmasq_args,
    firewall_rules,
    gateway_cidr,
    gateway_ip,
    validate_interface_name,
    validate_subnet,
)
from services.dhcp_gateway_preflight import PreflightMixin
from services.dhcp_gateway_runtime import RuntimeMixin

logger = logging.getLogger("nettap.services.dhcp_gateway")


class DhcpGatewayManager(PreflightMixin, RuntimeMixin, HostNetOps, CaptureManager):
    """Runs NetTap as the DHCP server and gateway for its own subnet."""

    def __init__(
        self,
        config: CaptureConfig,
        config_path: str | None = None,
        netplan_dir: str | None = None,
        systemd_dir: str | None = None,
        sysctl_dir: str | None = None,
        etc_dir: str | None = None,
        lease_dir: str | None = None,
        sys_net: str | None = None,
    ) -> None:
        self._config = config
        self._config_path = config_path
        self._dirs = BootDirs(
            netplan=netplan_dir or os.environ.get("HOST_NETPLAN_DIR", ""),
            sysctl=sysctl_dir or os.environ.get("HOST_SYSCTL_DIR", ""),
            etc=etc_dir or "/etc/nettap",
            systemd=systemd_dir or os.environ.get("HOST_SYSTEMD_DIR", ""),
        )
        self._lease_dir = lease_dir or "/var/lib/nettap/dhcp"
        self._sys_net = sys_net or os.environ.get("HOST_SYS_NET", "/host/sys/class/net")
        self.ip_forward_path = "/proc/sys/net/ipv4/ip_forward"
        self._dnsmasq = DnsmasqProcess()
        self._backend: str | None = None
        self._save_error = ""
        # Why reconcile kept dnsmasq off (another DHCP server answered), or ""
        self._dhcp_held = ""
        # Serialises enable / disable / teardown / reconcile
        self._lock = asyncio.Lock()

        logger.info(
            "DhcpGatewayManager initialized: interface=%s subnet=%s routing=%s "
            "dhcp=%s netplan=%s systemd=%s sysctl=%s",
            config.interface,
            config.dhcp_subnet,
            self.routing_active,
            config.dhcp_enabled,
            self._dirs.netplan or "(not mounted)",
            self._dirs.systemd or "(not mounted)",
            self._dirs.sysctl or "(not mounted)",
        )

    # -------------------------------------------------------------------
    # State
    # -------------------------------------------------------------------

    @property
    def routing_active(self) -> bool:
        """Routing is on once enable has recorded the router (upstream gateway)."""
        return self._config.mode == CaptureMode.DHCP_GATEWAY and bool(
            self._config.dhcp_upstream_gateway
        )

    def _upstream(self) -> dict | None:
        """The recorded router-side address and gateway, or None."""
        if not (
            self._config.dhcp_upstream_address and self._config.dhcp_upstream_gateway
        ):
            return None
        return {
            "address": self._config.dhcp_upstream_address,
            "gateway": self._config.dhcp_upstream_gateway,
        }

    def _validated(self) -> tuple[str, str]:
        """(interface, canonical subnet) from config. Raises ValueError."""
        return (
            validate_interface_name(self._config.interface),
            validate_subnet(self._config.dhcp_subnet),
        )

    def _validated_upstream(self) -> tuple[str, str]:
        """(upstream CIDR, router IP) from config, canonical. Raises ValueError."""
        address = ipaddress.IPv4Interface(self._config.dhcp_upstream_address)
        return address.with_prefixlen, str(
            ipaddress.IPv4Address(self._config.dhcp_upstream_gateway)
        )

    # -------------------------------------------------------------------
    # Enable / disable / status (preflight() comes from PreflightMixin)
    # -------------------------------------------------------------------

    async def enable(self) -> tuple[bool, dict]:
        """Turn on routing + DHCP after a fresh preflight.

        Returns:
            (True, status body) on success.
            (False, {"error", "checks"}) when a blocking check failed (refused).
            (False, {"error"}) when applying failed; partial state is rolled
            back and the saved config is left as it was.
        """
        async with self._lock:
            pre = await self.preflight()
            if not pre["ready"]:
                failed = [
                    c["message"]
                    for c in pre["checks"]
                    if c["blocking"] and not c["passed"]
                ]
                logger.warning("DHCP gateway enable refused: %s", failed)
                return False, {
                    "error": "DHCP gateway mode can't be turned on yet. "
                    + " ".join(failed),
                    "checks": pre["checks"],
                }
            unmounted = [d or "(not set)" for d in self._dirs if not os.path.isdir(d)]
            if unmounted:
                # Without boot persistence NetTap would lose its address on reboot
                return False, {
                    "error": "Host config folders are not available to the daemon "
                    f"({', '.join(unmounted)}), so the settings would not survive a reboot."
                }

            undo: list = []
            try:
                await self._apply(pre, undo)
            except Exception as exc:
                logger.error("DHCP gateway enable failed, rolling back: %s", exc)
                await self._rollback(undo)
                return False, {"error": f"Could not turn on DHCP gateway mode: {exc}"}
        logger.info("DHCP gateway enabled on %s (%s)", pre["interface"], pre["subnet"])
        return True, await self.status()

    async def _apply(self, pre: dict, undo: list) -> None:
        """Apply runtime state, persistence, config and dnsmasq; record undo steps."""
        iface, subnet, backend = (
            pre["interface"],
            pre["subnet"],
            pre["firewall_backend"],
        )
        upstream = pre["upstream"]
        own_cidr = gateway_cidr(subnet)

        if own_cidr not in await self._iface_cidrs(iface):
            rc, _, err = await self._run_nsenter(
                "ip", "addr", "add", own_cidr, "dev", iface
            )
            if rc != 0:
                raise RuntimeError(
                    f"Could not add {own_cidr} to {iface}: {err.strip()}"
                )
            undo.append(
                lambda: self._run_nsenter("ip", "addr", "del", own_cidr, "dev", iface)
            )

        for rule in firewall_rules(subnet, iface):
            if await self._ensure_rule(backend, rule):
                undo.append(lambda rule=rule: self._delete_rule(backend, rule))

        await self._disable_gro(iface)

        files = boot_files(
            self._dirs, iface, subnet, upstream["address"], upstream["gateway"]
        )
        for path, content, mode in files:
            existed = os.path.lexists(path)
            write_file_atomic(path, content, mode)
            if not existed:
                undo.append(lambda path=path: remove_path(path))
        # Link target is the host path (container paths dangle on the host)
        link = os.path.join(self._dirs.systemd, WANTS_LINK)
        existed = os.path.lexists(link)
        replace_symlink(HOST_UNIT_PATH, link)
        if not existed:
            undo.append(lambda: remove_path(link))

        old_config = self._config
        new_config = replace(
            old_config,
            dhcp_upstream_address=upstream["address"],
            dhcp_upstream_gateway=upstream["gateway"],
            dhcp_enabled=True,
        )
        save_capture_config(new_config, self._config_path)
        undo.append(lambda: save_capture_config(old_config, self._config_path))

        args = dnsmasq_args(iface, subnet, upstream["gateway"], self._lease_path())
        if await self._dnsmasq.start(args, self._lease_dir):
            undo.append(self._dnsmasq.stop)
        self._config = new_config
        self._save_error = ""
        self._dhcp_held = ""

    async def _rollback(self, undo: list) -> None:
        """Run undo steps newest first; one failing step doesn't stop the rest."""
        for step in reversed(undo):
            try:
                result = step()
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                logger.error("DHCP gateway rollback step failed: %s", exc)

    async def disable(self) -> dict:
        """Stop the DHCP server. Routing stays, so existing leases keep working."""
        async with self._lock:
            await self._dnsmasq.stop()
            self._config = replace(self._config, dhcp_enabled=False)
            try:
                save_capture_config(self._config, self._config_path)
                self._save_error = ""
            except OSError as exc:
                logger.error(
                    "Could not save capture config after disabling DHCP: %s", exc
                )
                self._save_error = (
                    "DHCP is off, but the setting could not be saved, so it will "
                    f"turn back on when NetTap restarts ({exc})."
                )
        logger.info("DHCP server disabled (routing stays active)")
        return await self.status()

    async def status(self) -> dict:
        """Current DHCP gateway state, leases and issues."""
        try:
            own_ip = gateway_ip(self._config.dhcp_subnet)
        except ValueError:
            own_ip = ""
        return {
            "interface": self._config.interface,
            "subnet": self._config.dhcp_subnet,
            "gateway_ip": own_ip,
            "upstream": self._upstream(),
            "routing_active": self.routing_active,
            "dhcp_enabled": self._config.dhcp_enabled,
            "dhcp_server_running": self._dnsmasq.running,
            "leases": self._read_leases(),
            "issues": await self._issues(),
        }

    # -------------------------------------------------------------------
    # CaptureManager interface
    # -------------------------------------------------------------------

    async def setup(self) -> dict:
        """Daemon start: re-apply runtime state and start dnsmasq if enabled."""
        if not self.routing_active:
            logger.info("DHCP gateway not enabled yet; nothing to set up")
            return {
                "success": True,
                "routing_active": False,
                "warnings": [],
                "errors": [],
            }
        try:
            iface, _ = self._validated()
        except ValueError as exc:
            return {
                "success": False,
                "routing_active": True,
                "warnings": [],
                "errors": [str(exc)],
            }
        warning = await self._disable_gro(iface)
        await self.reconcile()
        issues = await self._issues()
        return {
            "success": not issues,
            "routing_active": True,
            "dhcp_server_running": self._dnsmasq.running,
            "warnings": [warning] if warning else [],
            "errors": issues,
        }

    async def teardown(self) -> dict:
        """Remove everything: dnsmasq, rules, gateway address, boot files, upstream.

        NetTap's own router-side address is left alone, so the dashboard stays
        reachable until the next reboot.
        """
        errors: list[str] = []
        async with self._lock:
            await self._dnsmasq.stop()
            try:
                iface, subnet = self._validated()
            except ValueError as exc:
                iface = subnet = ""
                errors.append(f"Skipped rule and address cleanup: {exc}")
            if iface:
                # Only the detected backend: running the other one could
                # create empty legacy tables next to Docker's
                backend = self._backend or await self.detect_firewall_backend()
                if backend is None:
                    errors.append(
                        "Docker's DOCKER-USER chain was not found, so the routing "
                        "firewall rules were not removed (they go away on reboot)."
                    )
                for rule in firewall_rules(subnet, iface) if backend else []:
                    err = await self._delete_rule(backend, rule)
                    if err:
                        errors.append(err)
                own_cidr = gateway_cidr(subnet)
                if own_cidr in await self._iface_cidrs(iface):
                    rc, _, err = await self._run_nsenter(
                        "ip", "addr", "del", own_cidr, "dev", iface
                    )
                    if rc != 0:
                        errors.append(
                            f"Could not remove {own_cidr} from {iface}: {err.strip()}"
                        )
            for path in boot_paths(self._dirs):
                try:
                    remove_path(path)
                except OSError as exc:
                    errors.append(f"Could not delete {path}: {exc}")
            cleared = {
                "dhcp_upstream_address": "",
                "dhcp_upstream_gateway": "",
                "dhcp_enabled": False,
            }
            self._config = replace(self._config, **cleared)
            try:
                # Re-read first so a mode the wizard already saved is kept
                current = load_capture_config(self._config_path)
                save_capture_config(replace(current, **cleared), self._config_path)
            except OSError as exc:
                errors.append(f"Could not save capture config: {exc}")

        if errors:
            logger.warning("DHCP gateway teardown had errors: %s", errors)
        else:
            logger.info("DHCP gateway torn down")
        return {
            "torn_down": not errors,
            "interface": self._config.interface,
            "errors": errors,
        }

    def get_capture_interface(self) -> str:
        """The LAN NIC: capture runs on it with a device-leg BPF filter."""
        return self._config.interface

    async def get_stats(self) -> CaptureStats:
        """LAN NIC counters from sysfs."""
        return read_iface_stats(self._sys_net, self._config.interface)

    @property
    def mode(self) -> CaptureMode:
        """The capture mode this manager implements."""
        return CaptureMode.DHCP_GATEWAY
