"""
NetTap DHCP Gateway — pure network helpers (no I/O).

Validation, address math, the firewall rule list, and the text of every file
the DHCP gateway mode writes to the host. Kept free of I/O so each piece can
be unit-tested on its own and reused by the API layer for input validation.

Every value that ends up in a host command or file is validated here first:
interface names against ``^[A-Za-z0-9._-]{1,15}$`` and subnets with
``ipaddress`` (RFC1918 only, prefix /16 to /28, exact network address).
"""

import ipaddress
import os
import re
import shlex
import textwrap
from typing import NamedTuple

# Tag on every firewall rule, so the rules are easy to find and remove
RULE_COMMENT = "nettap-dhcp-gateway"

# Boot file names, and the host paths (as seen from the host, not the container)
NETPLAN_FILE = "90-nettap-dhcp-gateway.yaml"
SYSCTL_FILE = "99-nettap-dhcp-gateway.conf"
SCRIPT_FILE = "dhcp-gateway-firewall.sh"
UNIT_FILE = "nettap-dhcp-gateway.service"
WANTS_LINK = os.path.join("multi-user.target.wants", UNIT_FILE)
HOST_FIREWALL_SCRIPT = "/etc/nettap/" + SCRIPT_FILE
HOST_UNIT_PATH = "/etc/systemd/system/" + UNIT_FILE

# First host offset handed out by DHCP: .1 is the gateway, .2-.9 stay free
# for the user's static assignments.
_POOL_START_OFFSET = 10
_MIN_PREFIX = 16
_MAX_PREFIX = 28
_LEASE_TIME = "1h"
# Unprivileged account dnsmasq drops to (Debian base-passwd, uid/gid 65534)
DNSMASQ_USER = "nobody"
DNSMASQ_GROUP = "nogroup"

_IFACE_RE = re.compile(r"[A-Za-z0-9._-]{1,15}")
_RFC1918 = (
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
)


def validate_interface_name(name: str) -> str:
    """Return ``name`` if it is a safe Linux interface name, else raise ValueError."""
    # fullmatch, not ^...$: "$" would also accept a trailing newline.
    # "." / ".." and a leading "-" are refused too (sysfs paths, CLI options).
    if (
        not isinstance(name, str)
        or not _IFACE_RE.fullmatch(name)
        or name in (".", "..")
        or name.startswith("-")
    ):
        raise ValueError(
            f"'{name}' is not a valid network interface name "
            "(1-15 letters, digits, '.', '_' or '-')."
        )
    return name


def _network(cidr: str) -> ipaddress.IPv4Network:
    """Parse and validate a DHCP subnet; see validate_subnet."""
    if not isinstance(cidr, str) or "/" not in cidr:
        raise ValueError(f"'{cidr}' is not a subnet. Use the form 10.77.0.0/24.")
    try:
        net = ipaddress.IPv4Network(cidr, strict=True)
    except ipaddress.NetmaskValueError:
        raise ValueError(f"'{cidr}' has an invalid prefix length.") from None
    except ValueError:
        raise ValueError(
            f"'{cidr}' is not a valid subnet. It must be a network address "
            "such as 10.77.0.0/24 (the last part must be 0 for a /24)."
        ) from None
    if not any(net.subnet_of(private) for private in _RFC1918):
        raise ValueError(
            f"{net} is not a private subnet. Use one inside 10.0.0.0/8, "
            "172.16.0.0/12 or 192.168.0.0/16."
        )
    if not _MIN_PREFIX <= net.prefixlen <= _MAX_PREFIX:
        raise ValueError(
            f"{net} has a /{net.prefixlen} prefix. Use a prefix between "
            f"/{_MIN_PREFIX} and /{_MAX_PREFIX} (for example /24)."
        )
    return net


def validate_subnet(cidr: str) -> str:
    """Validate a DHCP subnet and return it in canonical form.

    Rules: private (RFC1918), prefix /16 to /28, and an exact network address
    (``10.77.0.5/24`` is refused). Raises ValueError with a plain-English
    message that can be shown to the user.
    """
    return str(_network(cidr))


def gateway_ip(subnet: str) -> str:
    """NetTap's own address on the DHCP subnet: the first host (``.1``)."""
    return str(_network(subnet).network_address + 1)


def gateway_cidr(subnet: str) -> str:
    """The gateway address with the subnet prefix, e.g. ``10.77.0.1/24``."""
    net = _network(subnet)
    return f"{net.network_address + 1}/{net.prefixlen}"


def pool_range(subnet: str) -> tuple[str, str]:
    """First and last address handed out by DHCP (host offset 10 to last host)."""
    net = _network(subnet)
    return (
        str(net.network_address + _POOL_START_OFFSET),
        str(net.broadcast_address - 1),
    )


def capture_filter(subnet: str) -> str:
    """BPF filter that keeps only the device leg (pre-NAT) plus DHCP broadcasts."""
    return f"net {validate_subnet(subnet)} or udp port 67 or udp port 68"


def firewall_rules(
    subnet: str, iface: str
) -> list[tuple[str, str, str, tuple[str, ...]]]:
    """The routing/NAT rules, as ``(table, chain, "-I" or "-A", rule_args)``.

    Every rule is inserted (``-I``) so it sits ahead of anything that could
    end the chain early (Docker's RETURN, ufw ACCEPTs). The rules only match
    the DHCP subnet on ``iface``, so their position can't affect other traffic.
    Both DOCKER-USER rules pin ``-i`` and ``-o`` to ``iface`` (the one-armed
    path), so a device on the subnet can't reach Docker bridges or other NICs.
    """
    net = validate_subnet(subnet)
    validate_interface_name(iface)
    tag = ("-m", "comment", "--comment", RULE_COMMENT)
    return [
        (
            "filter",
            "DOCKER-USER",
            "-I",
            ("-i", iface, "-o", iface, "-s", net, *tag, "-j", "ACCEPT"),
        ),
        (
            "filter",
            "DOCKER-USER",
            "-I",
            (
                "-i",
                iface,
                "-o",
                iface,
                "-d",
                net,
                "-m",
                "conntrack",
                "--ctstate",
                "RELATED,ESTABLISHED",
                *tag,
                "-j",
                "ACCEPT",
            ),
        ),
        (
            "nat",
            "POSTROUTING",
            "-I",
            ("-o", iface, "-s", net, "!", "-d", net, *tag, "-j", "MASQUERADE"),
        ),
        (
            "filter",
            "OUTPUT",
            "-I",
            ("-o", iface, "-p", "icmp", "--icmp-type", "redirect", *tag, "-j", "DROP"),
        ),
    ]


def dnsmasq_args(
    iface: str, subnet: str, upstream_gateway: str, lease_file: str
) -> list[str]:
    """dnsmasq command line: DHCP only (``--port=0``), DNS handed to the router."""
    validate_interface_name(iface)
    net = _network(subnet)
    dns = str(ipaddress.IPv4Address(upstream_gateway))
    start, end = pool_range(subnet)
    return [
        "dnsmasq",
        "--keep-in-foreground",
        "--port=0",
        "--conf-file=/dev/null",
        # No pid file: the daemon supervises the child, and as nobody dnsmasq
        # couldn't chown one in the root-owned /var/run anyway
        "--pid-file",
        # Drops to nobody:nogroup after opening its sockets and lease file
        # (needs SETUID/SETGID in the daemon's cap_add; KILL lets it stop dnsmasq)
        f"--user={DNSMASQ_USER}",
        f"--group={DNSMASQ_GROUP}",
        f"--interface={iface}",
        "--except-interface=lo",
        "--bind-interfaces",
        "--dhcp-authoritative",
        f"--dhcp-range={start},{end},{net.netmask},{_LEASE_TIME}",
        f"--dhcp-option=option:router,{gateway_ip(subnet)}",
        f"--dhcp-option=option:dns-server,{dns}",
        f"--dhcp-leasefile={lease_file}",
        "--log-facility=-",
    ]


def render_netplan(
    iface: str, upstream_cidr: str, upstream_gateway: str, gateway_cidr: str
) -> str:
    """Netplan YAML: static upstream + gateway address, default route, DNS."""
    validate_interface_name(iface)
    upstream = ipaddress.IPv4Interface(upstream_cidr)
    router = ipaddress.IPv4Address(upstream_gateway)
    own = ipaddress.IPv4Interface(gateway_cidr)
    return textwrap.dedent(f"""\
        # NetTap DHCP gateway configuration — auto-generated
        # Keeps NetTap's address static once the router's DHCP is off
        # Do not edit manually; removed when DHCP gateway mode is turned off
        network:
          version: 2
          renderer: networkd
          ethernets:
            {iface}:
              dhcp4: false
              addresses:
                - {upstream.with_prefixlen}
                - {own.with_prefixlen}
              routes:
                - to: default
                  via: {router}
              nameservers:
                addresses:
                  - {router}
    """)


def render_sysctl(iface: str) -> str:
    """sysctl.d config: forwarding on, ICMP redirects off (all, default, iface)."""
    validate_interface_name(iface)
    # Slash form for the per-interface key: dots in VLAN names (eth0.10)
    # would otherwise be read as key separators.
    return textwrap.dedent(f"""\
        # NetTap DHCP gateway sysctl — auto-generated
        net.ipv4.ip_forward = 1
        net.ipv4.conf.all.send_redirects = 0
        net.ipv4.conf.default.send_redirects = 0
        net/ipv4/conf/{iface}/send_redirects = 0
    """)


def render_firewall_script(subnet: str, iface: str) -> str:
    """POSIX sh script that re-adds the firewall rules at boot with host iptables.

    Waits up to 60 s for Docker's DOCKER-USER chain, checks each rule with
    ``-C`` before adding it, and always exits 0 so it never fails the unit.
    """
    lines = []
    for table, chain, action, args in firewall_rules(subnet, iface):
        quoted = " ".join(shlex.quote(a) for a in args)
        lines.append(f"add_rule {table} {chain} {action} {quoted}")
    rules = "\n".join(lines)
    return (
        textwrap.dedent("""\
            #!/bin/sh
            # NetTap DHCP gateway firewall rules — auto-generated
            # Restores routing at boot without the NetTap daemon.
            # Never fails: a missing rule must not block boot.
            PATH=/usr/sbin:/usr/bin:/sbin:/bin

            i=0
            while ! iptables -w -S DOCKER-USER >/dev/null 2>&1; do
                i=$((i + 1))
                if [ "$i" -ge 60 ]; then
                    echo "nettap-dhcp-gateway: DOCKER-USER chain not found after 60s" >&2
                    break
                fi
                sleep 1
            done

            add_rule() {
                table=$1
                chain=$2
                action=$3
                shift 3
                if ! iptables -w -t "$table" -C "$chain" "$@" 2>/dev/null; then
                    iptables -w -t "$table" "$action" "$chain" "$@" ||
                        echo "nettap-dhcp-gateway: could not add a rule to $table/$chain" >&2
                fi
            }

        """)
        + rules
        + "\n\nexit 0\n"
    )


def render_systemd_unit() -> str:
    """Oneshot unit that runs the firewall script after Docker starts."""
    return textwrap.dedent(f"""\
        # NetTap DHCP gateway service — auto-generated
        # Restores the routing firewall rules at boot
        [Unit]
        Description=NetTap DHCP gateway firewall rules
        After=docker.service
        Wants=docker.service

        [Service]
        Type=oneshot
        RemainAfterExit=yes
        ExecStart={HOST_FIREWALL_SCRIPT}

        [Install]
        WantedBy=multi-user.target
    """)


class BootDirs(NamedTuple):
    """Where the boot files go, as mounted in the daemon container."""

    netplan: str
    sysctl: str
    etc: str
    systemd: str


def boot_files(
    dirs: BootDirs, iface: str, subnet: str, upstream_cidr: str, upstream_gateway: str
) -> list[tuple[str, str, int]]:
    """``(path, content, mode)`` for each boot file (not the enable symlink)."""
    netplan = render_netplan(
        iface, upstream_cidr, upstream_gateway, gateway_cidr(subnet)
    )
    return [
        # 0600: netplan warns about world-readable files
        (os.path.join(dirs.netplan, NETPLAN_FILE), netplan, 0o600),
        (os.path.join(dirs.sysctl, SYSCTL_FILE), render_sysctl(iface), 0o644),
        (
            os.path.join(dirs.etc, SCRIPT_FILE),
            render_firewall_script(subnet, iface),
            0o755,
        ),
        (os.path.join(dirs.systemd, UNIT_FILE), render_systemd_unit(), 0o644),
    ]


def boot_paths(dirs: BootDirs) -> list[str]:
    """Every boot file plus the enable symlink, skipping dirs that aren't set."""
    pairs = [
        (dirs.netplan, NETPLAN_FILE),
        (dirs.sysctl, SYSCTL_FILE),
        (dirs.etc, SCRIPT_FILE),
        (dirs.systemd, UNIT_FILE),
        (dirs.systemd, WANTS_LINK),
    ]
    return [os.path.join(d, name) for d, name in pairs if d]


def parse_leases(text: str) -> list[dict]:
    """Parse a dnsmasq lease file into ``{mac, ip, hostname, expires}`` dicts.

    Line format: ``<expiry epoch> <mac> <ip> <hostname|*> <client-id|*>``.
    Malformed lines (and the DHCPv6 ``duid`` line) are skipped.
    """
    leases = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        try:
            expires = int(parts[0])
            ip = str(ipaddress.ip_address(parts[2]))
        except ValueError:
            continue
        leases.append(
            {
                "mac": parts[1].lower(),
                "ip": ip,
                "hostname": "" if parts[3] == "*" else parts[3],
                "expires": expires,
            }
        )
    return leases
