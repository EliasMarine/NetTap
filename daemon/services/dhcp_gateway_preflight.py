"""
NetTap DHCP Gateway — preflight checks.

Everything that must be true before NetTap may hand out addresses and route:
the NIC is up, NetTap has an address and default route on the router's
network, no other DHCP server answers, the subnet collides with nothing,
forwarding is on, and Docker's DOCKER-USER chain exists. IPv6 router
advertisements only warn. Read-only: nothing on the host is changed.
"""

import ipaddress
import logging
import os

from services.dhcp_gateway_host import read_sysfs
from services.dhcp_gateway_net import gateway_ip
from services.dhcp_probe import probe_dhcp_servers

logger = logging.getLogger("nettap.services.dhcp_gateway")

_CHECK_NAMES = (
    "interface_up",
    "upstream_detected",
    "no_other_dhcp",
    "no_subnet_conflict",
    "ip_forward",
    "firewall_backend",
)


def _check(name: str, passed: bool, message: str, blocking: bool = True) -> dict:
    return {"name": name, "passed": passed, "blocking": blocking, "message": message}


class PreflightMixin:
    """``preflight()`` for DhcpGatewayManager.

    Uses the manager's config, ``_validated()``, ``_upstream()``,
    ``routing_active``, ``_sys_net``, ``ip_forward_path`` and the HostNetOps
    queries.
    """

    async def preflight(self) -> dict:
        """Run every check that must pass before enabling. See design §6.2."""
        iface, subnet = self._config.interface, self._config.dhcp_subnet
        try:
            iface, subnet = self._validated()
        except ValueError as exc:
            # Nothing is safe to query with an invalid name or subnet
            checks = [_check(n, False, str(exc)) for n in _CHECK_NAMES]
            return self._preflight_result(
                iface, subnet, "", None, [], [], False, False, None, checks
            )

        net = ipaddress.IPv4Network(subnet)
        own_ip = gateway_ip(subnet)
        all_addrs = await self.inet_addrs()
        link_up = read_sysfs(os.path.join(self._sys_net, iface, "operstate")) == "up"
        upstream = await self._detect_upstream(iface, net)
        if upstream is None and self.routing_active:
            # The live address may have lapsed; reconcile re-adds the recorded one
            upstream = self._upstream()
        conflicts = []
        for dev, addr in all_addrs:
            ours = dev == iface and str(addr.ip) == own_ip
            item = {"interface": dev, "network": str(addr.network)}
            if addr.network.overlaps(net) and not ours and item not in conflicts:
                conflicts.append(item)
        own_ips = {str(addr.ip) for _, addr in all_addrs} | {own_ip}
        others, probe_error = await self._probe_others(iface, own_ips)
        ipv6_ra = await self._ipv6_ra(iface)
        ip_forward = read_sysfs(self.ip_forward_path) == "1"
        backend = await self.detect_firewall_backend()

        servers = ", ".join(o["server_ip"] for o in others)
        checks = [
            _check(
                "interface_up",
                link_up,
                f"{iface} is connected."
                if link_up
                else f"{iface} is down. Plug it into your router.",
            ),
            _check(
                "upstream_detected",
                upstream is not None,
                f"NetTap is {upstream['address']} on your router's network "
                f"(router {upstream['gateway']})."
                if upstream
                else f"NetTap has no address or default route on {iface}. "
                "Make sure this port is plugged into your router.",
            ),
            _check(
                "no_other_dhcp",
                not others and not probe_error,
                f"NetTap could not check for other DHCP servers: {probe_error}"
                if probe_error
                else f"Your router's DHCP server is still on ({servers})."
                if others
                else "No other DHCP server answered.",
            ),
            _check(
                "no_subnet_conflict",
                not conflicts,
                f"{subnet} overlaps a network already in use ("
                + ", ".join(f"{c['network']} on {c['interface']}" for c in conflicts)
                + "). Pick a different subnet."
                if conflicts
                else f"{subnet} does not overlap any existing network.",
            ),
            _check(
                "ip_forward",
                ip_forward,
                "IP forwarding is on."
                if ip_forward
                else "IP forwarding is off on this machine (net.ipv4.ip_forward=0).",
            ),
            _check(
                "firewall_backend",
                backend is not None,
                f"Docker's firewall chain found ({backend})."
                if backend
                else "Docker's DOCKER-USER firewall chain was not found. "
                "Make sure Docker is running.",
            ),
            _check(
                "ipv6_bypass",
                not ipv6_ra,
                "Your router hands out IPv6 addresses, so IPv6 traffic will go "
                "straight to the router and NetTap won't see it. Turn off IPv6 "
                "on the router for full visibility."
                if ipv6_ra
                else "No IPv6 router advertisements seen.",
                blocking=False,
            ),
        ]
        return self._preflight_result(
            iface,
            subnet,
            own_ip,
            upstream,
            conflicts,
            others,
            ipv6_ra,
            ip_forward,
            backend,
            checks,
        )

    @staticmethod
    def _preflight_result(
        iface,
        subnet,
        own_ip,
        upstream,
        conflicts,
        others,
        ipv6_ra,
        ip_forward,
        backend,
        checks,
    ) -> dict:
        return {
            "interface": iface,
            "subnet": subnet,
            "gateway_ip": own_ip,
            "upstream": upstream,
            "subnet_conflicts": conflicts,
            "other_dhcp_servers": others,
            "ipv6_router_advertisements": ipv6_ra,
            "ip_forward": ip_forward,
            "firewall_backend": backend,
            "checks": checks,
            "ready": all(c["passed"] for c in checks if c["blocking"]),
        }

    async def _detect_upstream(
        self, iface: str, net: ipaddress.IPv4Network
    ) -> dict | None:
        """NetTap's router-side address: the one whose network holds the default gateway."""
        gateways = [
            r.get("gateway")
            for r in await self.ip_json("-4", "route", "show", "default")
            if isinstance(r, dict) and r.get("dev") == iface and r.get("gateway")
        ]
        addrs = [addr for _, addr in await self.inet_addrs(iface) if addr.ip not in net]
        for gateway in gateways:
            try:
                router = ipaddress.IPv4Address(gateway)
            except ValueError:
                continue
            for addr in addrs:
                if router in addr.network:
                    return {"address": addr.with_prefixlen, "gateway": str(router)}
        return None

    async def probe_other_dhcp(self) -> tuple[list[dict], str]:
        """Fresh probe on the LAN NIC: (other DHCP servers, error string).

        NetTap's own addresses are excluded, so a running dnsmasq doesn't count.
        An invalid saved config comes back as an error, never as "none".
        """
        try:
            iface, subnet = self._validated()
        except ValueError as exc:
            return [], str(exc)
        own_ips = {str(addr.ip) for _, addr in await self.inet_addrs()}
        return await self._probe_others(iface, own_ips | {gateway_ip(subnet)})

    async def _probe_others(
        self, iface: str, own_ips: set[str]
    ) -> tuple[list[dict], str]:
        """DHCP servers other than NetTap, plus an error string if the probe failed."""
        mac = read_sysfs(os.path.join(self._sys_net, iface, "address"))
        try:
            offers = await probe_dhcp_servers(iface, mac)
        except (OSError, ValueError) as exc:
            # Unknown is not "none": the check fails so enable is refused
            logger.warning("DHCP probe on %s failed: %s", iface, exc)
            return [], str(exc)
        return [o for o in offers if o["server_ip"] not in own_ips], ""

    async def _ipv6_ra(self, iface: str) -> bool:
        """True if the router advertises IPv6 (RA default route or SLAAC address)."""
        for route in await self.ip_json("-6", "route", "show", "default"):
            if (
                isinstance(route, dict)
                and route.get("dev") == iface
                and route.get("protocol") == "ra"
            ):
                return True
        for link in await self.ip_json(
            "-6", "addr", "show", "dev", iface, "scope", "global"
        ):
            if isinstance(link, dict) and any(
                a.get("dynamic") for a in link.get("addr_info", [])
            ):
                return True
        return False
