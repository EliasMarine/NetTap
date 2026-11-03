"""
NetTap DHCP Probe — find every DHCP server answering on a LAN.

Sends one real DHCPDISCOVER (broadcast flag set) from a raw AF_PACKET socket
and collects the OFFERs that come back. DHCP gateway mode must never run next
to another DHCP server, so the preflight and ``enable`` both run this probe.

The probe never sends a DHCPREQUEST, so no server creates a lease for it.
The daemon runs with ``network_mode: host`` and NET_RAW, so the socket opens
straight in the host network namespace (no nsenter needed).
"""

import asyncio
import ipaddress
import logging
import re
import secrets
import socket
import struct
import time

from services.dhcp_gateway_net import validate_interface_name

logger = logging.getLogger("nettap.services.dhcp_probe")

# socket.AF_PACKET only exists on Linux; 17 is its value there
_AF_PACKET = getattr(socket, "AF_PACKET", 17)
_ETH_P_IP = 0x0800

_ETH_HDR = 14
_UDP_HDR = 8
_BOOTP_FIXED = 236  # op .. file, before the magic cookie
_MAGIC_COOKIE = b"\x63\x82\x53\x63"
_MIN_BOOTP = 300  # some servers drop shorter requests (RFC 1542 minimum)
_DHCPDISCOVER = 1
_DHCPOFFER = 2

_MAC_RE = re.compile(r"[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}")


def _ip_checksum(header: bytes) -> int:
    """RFC 1071 ones' complement checksum over an IPv4 header."""
    total = sum(struct.unpack(f"!{len(header) // 2}H", header))
    while total > 0xFFFF:
        total = (total & 0xFFFF) + (total >> 16)
    return ~total & 0xFFFF


def build_discover(xid: int, mac: bytes) -> bytes:
    """Build a complete Ethernet frame carrying a DHCPDISCOVER.

    Broadcast Ethernet + IPv4 (0.0.0.0 -> 255.255.255.255) + UDP 68 -> 67,
    BOOTP with the broadcast flag, options 53=DISCOVER and 55=[1, 3, 6, 54].
    """
    if not 0 <= xid <= 0xFFFFFFFF:
        raise ValueError("xid must fit in 32 bits")
    if len(mac) != 6:
        raise ValueError("mac must be 6 bytes")

    options = bytes([53, 1, _DHCPDISCOVER]) + bytes([55, 4, 1, 3, 6, 54]) + bytes([255])
    bootp = (
        struct.pack(
            "!BBBBIHH4s4s4s4s16s64s128s",
            1,  # op: BOOTREQUEST
            1,  # htype: Ethernet
            6,  # hlen
            0,  # hops
            xid,
            0,  # secs
            0x8000,  # flags: broadcast, so the OFFER reaches an address-less client
            b"\x00" * 4,  # ciaddr
            b"\x00" * 4,  # yiaddr
            b"\x00" * 4,  # siaddr
            b"\x00" * 4,  # giaddr
            mac + b"\x00" * 10,  # chaddr
            b"\x00" * 64,  # sname
            b"\x00" * 128,  # file
        )
        + _MAGIC_COOKIE
        + options
    )
    bootp = bootp.ljust(_MIN_BOOTP, b"\x00")  # pad option (0) up to the minimum

    udp = struct.pack("!HHHH", 68, 67, _UDP_HDR + len(bootp), 0) + bootp
    ip_header = struct.pack(
        "!BBHHHBBH4s4s",
        0x45,  # IPv4, 20-byte header
        0,
        20 + len(udp),
        0,
        0,
        64,  # TTL
        17,  # UDP
        0,  # checksum placeholder
        b"\x00\x00\x00\x00",
        b"\xff\xff\xff\xff",
    )
    checksum = _ip_checksum(ip_header)
    ip_header = ip_header[:10] + struct.pack("!H", checksum) + ip_header[12:]
    eth = b"\xff" * 6 + mac + struct.pack("!H", _ETH_P_IP)
    return eth + ip_header + udp


def _parse_options(data: bytes) -> dict[int, bytes]:
    """Parse DHCP options (code, length, value) until END or the data runs out."""
    options: dict[int, bytes] = {}
    i = 0
    while i < len(data):
        code = data[i]
        if code == 255:
            break
        if code == 0:
            i += 1
            continue
        if i + 1 >= len(data):
            break
        length = data[i + 1]
        value = data[i + 2 : i + 2 + length]
        if len(value) != length:
            break  # truncated option
        options.setdefault(code, value)
        i += 2 + length
    return options


def parse_offer(frame: bytes, xid: int) -> dict | None:
    """Return ``{"server_ip", "offered_ip"}`` if ``frame`` is an OFFER for ``xid``.

    Anything else (wrong ethertype, ports, op, xid, message type, or a
    truncated frame) returns None.
    """
    if len(frame) < _ETH_HDR + 20:
        return None
    if struct.unpack("!H", frame[12:14])[0] != _ETH_P_IP:
        return None
    ip = frame[_ETH_HDR:]
    if ip[0] >> 4 != 4 or ip[9] != 17:
        return None
    ihl = (ip[0] & 0x0F) * 4
    if ihl < 20 or len(ip) < ihl + _UDP_HDR + _BOOTP_FIXED + len(_MAGIC_COOKIE):
        return None
    src_port, dst_port = struct.unpack("!HH", ip[ihl : ihl + 4])
    if src_port != 67 or dst_port != 68:
        return None
    bootp = ip[ihl + _UDP_HDR :]
    if bootp[0] != 2 or struct.unpack("!I", bootp[4:8])[0] != xid:
        return None
    cookie_end = _BOOTP_FIXED + len(_MAGIC_COOKIE)
    if bootp[_BOOTP_FIXED:cookie_end] != _MAGIC_COOKIE:
        return None
    options = _parse_options(bootp[cookie_end:])
    if options.get(53) != bytes([_DHCPOFFER]):
        return None
    server_id = options.get(54)
    server_raw = server_id if server_id and len(server_id) == 4 else ip[12:16]
    return {
        "server_ip": str(ipaddress.IPv4Address(server_raw)),
        "offered_ip": str(ipaddress.IPv4Address(bootp[16:20])),
    }


def _parse_mac(mac: str) -> bytes:
    """``aa:bb:cc:dd:ee:ff`` -> 6 bytes, or ValueError."""
    if not isinstance(mac, str) or not _MAC_RE.fullmatch(mac):
        raise ValueError(f"'{mac}' is not a MAC address (aa:bb:cc:dd:ee:ff)")
    return bytes.fromhex(mac.replace(":", ""))


def _probe_blocking(iface: str, mac: bytes, xid: int, timeout: float) -> list[dict]:
    """Send one DISCOVER on ``iface`` and collect OFFERs until the deadline."""
    servers: list[dict] = []
    sock = socket.socket(_AF_PACKET, socket.SOCK_RAW, socket.htons(_ETH_P_IP))
    try:
        sock.bind((iface, _ETH_P_IP))
        sock.send(build_discover(xid, mac))
        deadline = time.monotonic() + timeout
        while (remaining := deadline - time.monotonic()) > 0:
            sock.settimeout(remaining)
            try:
                frame = sock.recv(4096)
            except socket.timeout:
                break
            offer = parse_offer(frame, xid)
            if offer and all(s["server_ip"] != offer["server_ip"] for s in servers):
                servers.append(offer)
    finally:
        sock.close()
    return servers


async def probe_dhcp_servers(iface: str, mac: str, timeout: float = 3.0) -> list[dict]:
    """Broadcast a DHCPDISCOVER on ``iface`` and list every server that answers.

    Returns one ``{"server_ip", "offered_ip"}`` per server (de-duplicated).
    Raises ValueError for a bad interface name or MAC, and OSError when the
    raw socket can't be used. Callers must treat an error as "unknown", never
    as "no other DHCP server".
    """
    validate_interface_name(iface)
    mac_bytes = _parse_mac(mac)
    xid = secrets.randbits(32)
    servers = await asyncio.to_thread(_probe_blocking, iface, mac_bytes, xid, timeout)
    logger.info(
        "DHCP probe on %s: %d server(s) answered %s",
        iface,
        len(servers),
        [s["server_ip"] for s in servers],
    )
    return servers
