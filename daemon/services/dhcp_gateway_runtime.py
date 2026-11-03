"""
NetTap DHCP Gateway — runtime inspection, reconcile and health.

Compares what is actually present on the host (addresses, default route,
firewall rules, dnsmasq) with what the saved config says should be there.
``reconcile()`` re-adds the missing pieces; ``get_health()`` and the status
issues report them in plain English.
"""

import logging
import os
from dataclasses import replace

from services.capture_config import save_capture_config
from services.capture_manager import CaptureHealth, CaptureMode
from services.dhcp_gateway_host import read_sysfs
from services.dhcp_gateway_net import (
    dnsmasq_args,
    firewall_rules,
    gateway_cidr,
    parse_leases,
    validate_interface_name,
)

logger = logging.getLogger("nettap.services.dhcp_gateway")

LEASE_FILE = "dnsmasq.leases"


class RuntimeMixin:
    """``reconcile()``, ``get_health()`` and the inspection behind status.

    Uses the manager's config, ``_validated()``, ``_validated_upstream()``,
    ``routing_active``, ``_lock``, ``_dnsmasq``, ``_save_error``,
    ``_dhcp_held``, ``_sys_net``, ``_lease_dir``, ``probe_other_dhcp()`` and
    the HostNetOps queries.
    """

    async def reconcile(self) -> None:
        """Re-add whatever went missing. Cheap, safe every 30 s, never raises."""
        if not self.routing_active or self._lock.locked():
            return
        try:
            async with self._lock:
                await self._reconcile_locked()
        except Exception:
            logger.exception("DHCP gateway reconcile failed")

    async def _reconcile_locked(self) -> None:
        iface, subnet = self._validated()
        upstream_cidr, router = self._validated_upstream()
        state = await self._inspect(iface, subnet)
        fixes = []
        # Upstream address before the route: the route needs it on-link
        if not state["upstream_addr"]:
            fixes.append(("addr", "add", upstream_cidr, "dev", iface))
        if not state["default_route"]:
            fixes.append(("route", "add", "default", "via", router, "dev", iface))
        if not state["gateway_addr"]:
            fixes.append(("addr", "add", gateway_cidr(subnet), "dev", iface))
        for args in fixes:
            rc, _, err = await self._run_nsenter("ip", *args)
            if rc == 0:
                logger.info("Reconcile: re-applied 'ip %s'", " ".join(args))
            else:
                logger.warning(
                    "Reconcile: 'ip %s' failed: %s", " ".join(args), err.strip()
                )
        for rule in state["missing_rules"]:
            try:
                await self._ensure_rule(state["backend"], rule)
                logger.info("Reconcile: re-added %s/%s firewall rule", rule[0], rule[1])
            except RuntimeError as exc:
                logger.warning("Reconcile: %s", exc)
        if self._config.dhcp_enabled and not self._dnsmasq.running:
            # Probe first: two DHCP servers on one LAN hand out clashing leases
            others, error = await self.probe_other_dhcp()
            if others or error:
                self._hold_dhcp(others, error)
                return
            logger.warning("Reconcile: dnsmasq is not running, restarting it")
            await self._dnsmasq.start(
                dnsmasq_args(iface, subnet, router, self._lease_path()), self._lease_dir
            )
            if self._dnsmasq.running:
                self._dhcp_held = ""

    def _hold_dhcp(self, others: list[dict], error: str) -> None:
        """Keep dnsmasq off and say why; only a real second server turns the setting off.

        A probe error is often transient (NIC briefly down, ENOBUFS), and the
        router's DHCP is off by design, so persisting "off" would leave the LAN
        with no DHCP server at all. Hold for this tick and probe again next tick.
        """
        if not others:
            self._dhcp_held = (
                f"NetTap could not check for other DHCP servers ({error}), so it is "
                "holding its DHCP server off and will check again in a moment."
            )
            logger.warning("Not starting dnsmasq yet: %s", self._dhcp_held)
            return
        servers = ", ".join(o["server_ip"] for o in others)
        self._dhcp_held = (
            f"Another DHCP server ({servers}) is answering on your network, so NetTap "
            "kept its DHCP server off. Turn it back on from Go Live once your "
            "router's DHCP is off."
        )
        logger.warning("Not starting dnsmasq: %s", self._dhcp_held)
        self._config = replace(self._config, dhcp_enabled=False)
        try:
            save_capture_config(self._config, self._config_path)
        except OSError as exc:
            # Still safe: the next start probes again before starting dnsmasq
            logger.error("Could not save capture config after holding DHCP: %s", exc)

    async def get_health(self) -> CaptureHealth:
        """Link, routing pieces and dnsmasq, folded into one status."""
        iface = self._config.interface
        extra = {
            "subnet": self._config.dhcp_subnet,
            "routing_active": self.routing_active,
            "dhcp_server_running": self._dnsmasq.running,
            "lease_count": len(self._read_leases()),
        }
        try:
            validate_interface_name(iface)
        except ValueError as exc:
            return CaptureHealth(
                mode=CaptureMode.DHCP_GATEWAY.value,
                status="down",
                capture_interface=iface,
                link_up=False,
                promisc_enabled=False,
                issues=[str(exc)],
                extra=extra,
            )
        iface_dir = os.path.join(self._sys_net, iface)
        link_up = (
            read_sysfs(os.path.join(iface_dir, "operstate")) == "up"
            and read_sysfs(os.path.join(iface_dir, "carrier")) == "1"
        )
        try:
            promisc = bool(
                int(read_sysfs(os.path.join(iface_dir, "flags")), 16) & 0x100
            )
        except ValueError:
            promisc = False

        if not self.routing_active:
            status, issues = (
                "not_configured",
                ["DHCP gateway mode is not turned on yet."],
            )
        else:
            issues = await self._issues()
            if not link_up:
                status = "down"
                issues.insert(
                    0, f"{iface} has no link. Check the cable to your router."
                )
            else:
                status = "degraded" if issues else "normal"
        return CaptureHealth(
            mode=CaptureMode.DHCP_GATEWAY.value,
            status=status,
            capture_interface=iface,
            link_up=link_up,
            promisc_enabled=promisc,
            issues=issues,
            extra=extra,
        )

    async def _inspect(self, iface: str, subnet: str) -> dict:
        """Which routing pieces are present right now (read-only)."""
        upstream_cidr, router = self._validated_upstream()
        cidrs = await self._iface_cidrs(iface)
        routes = await self.ip_json("-4", "route", "show", "default")
        backend = self._backend or await self.detect_firewall_backend()
        missing = []
        if backend:
            for rule in firewall_rules(subnet, iface):
                if not await self._rule_present(backend, rule):
                    missing.append(rule)
        return {
            "gateway_addr": gateway_cidr(subnet) in cidrs,
            "upstream_addr": upstream_cidr in cidrs,
            "default_route": any(
                isinstance(r, dict)
                and r.get("gateway") == router
                and r.get("dev") == iface
                for r in routes
            ),
            "backend": backend,
            "missing_rules": missing,
        }

    async def _issues(self) -> list[str]:
        """Plain-English problems with the running gateway (empty when healthy)."""
        issues = [self._save_error] if self._save_error else []
        if not self.routing_active:
            return issues
        if self._dhcp_held:
            issues.append(self._dhcp_held)
        try:
            iface, subnet = self._validated()
            state = await self._inspect(iface, subnet)
        except ValueError as exc:
            return issues + [f"The saved DHCP gateway settings are invalid: {exc}"]
        if not state["upstream_addr"]:
            issues.append(
                f"NetTap's address {self._config.dhcp_upstream_address} is missing from {iface}."
            )
        if not state["default_route"]:
            issues.append(
                f"The default route via {self._config.dhcp_upstream_gateway} is missing."
            )
        if not state["gateway_addr"]:
            issues.append(
                f"The gateway address {gateway_cidr(subnet)} is missing from {iface}."
            )
        if state["backend"] is None:
            issues.append(
                "Docker's DOCKER-USER firewall chain was not found, so devices can't be routed."
            )
        elif state["missing_rules"]:
            issues.append(
                f"{len(state['missing_rules'])} routing firewall rule(s) are missing."
            )
        if self._config.dhcp_enabled and not self._dnsmasq.running:
            issues.append("The DHCP server is not running.")
        return issues

    def _lease_path(self) -> str:
        return os.path.join(self._lease_dir, LEASE_FILE)

    def _read_leases(self) -> list[dict]:
        try:
            with open(self._lease_path(), "r") as f:
                return parse_leases(f.read())
        except FileNotFoundError:
            return []
        except OSError as exc:
            logger.warning("Could not read DHCP leases: %s", exc)
            return []
