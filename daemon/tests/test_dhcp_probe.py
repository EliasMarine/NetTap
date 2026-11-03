"""
Tests for daemon/services/dhcp_probe.py

DISCOVER frames are checked byte by byte, OFFERs are parsed from hand-built
fixtures, and the raw-socket probe runs against a mocked socket — no
AF_PACKET access required.
"""

import asyncio
import os
import socket
import struct
import sys
import types
from unittest.mock import MagicMock, patch

# Ensure the daemon package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from services import dhcp_probe
from services.dhcp_probe import build_discover, parse_offer, probe_dhcp_servers

MAC = bytes.fromhex("aabbccddeeff")
XID = 0x12345678


def _ip(addr: str) -> bytes:
    return socket.inet_aton(addr)


def make_offer(
    xid=XID,
    server_id="192.168.1.1",
    offered="192.168.1.77",
    src_ip="192.168.1.1",
    msg_type=2,
    op=2,
    sport=67,
    dport=68,
    ethertype=0x0800,
    ihl=5,
    extra_options=b"",
):
    """Hand-built DHCP reply frame (Ethernet + IPv4 + UDP + BOOTP + options)."""
    options = b"\x63\x82\x53\x63" + bytes([53, 1, msg_type])
    if server_id:
        options += bytes([54, 4]) + _ip(server_id)
    options += extra_options + b"\xff"
    bootp = (
        bytes([op, 1, 6, 0])
        + struct.pack("!I", xid)
        + b"\x00" * 4  # secs + flags
        + b"\x00" * 4  # ciaddr
        + _ip(offered)  # yiaddr
        + b"\x00" * 8  # siaddr + giaddr
        + MAC
        + b"\x00" * 10
        + b"\x00" * 192  # sname + file
        + options
    )
    udp = struct.pack("!HHHH", sport, dport, 8 + len(bootp), 0) + bootp
    ip_opts = b"\x00" * ((ihl - 5) * 4)
    ip = (
        bytes([0x40 | ihl, 0])
        + struct.pack("!H", ihl * 4 + len(udp))
        + b"\x00" * 4
        + bytes([64, 17])
        + b"\x00\x00"
        + _ip(src_ip)
        + _ip("255.255.255.255")
        + ip_opts
    )
    eth = b"\xff" * 6 + bytes.fromhex("001122334455") + struct.pack("!H", ethertype)
    return eth + ip + udp


class TestBuildDiscover:
    def test_ethernet_header(self):
        frame = build_discover(XID, MAC)
        assert frame[0:6] == b"\xff" * 6
        assert frame[6:12] == MAC
        assert frame[12:14] == b"\x08\x00"

    def test_ip_header(self):
        frame = build_discover(XID, MAC)
        ip = frame[14:34]
        assert ip[0] == 0x45
        assert struct.unpack("!H", ip[2:4])[0] == len(frame) - 14
        assert ip[9] == 17  # UDP
        assert ip[12:16] == b"\x00\x00\x00\x00"
        assert ip[16:20] == b"\xff\xff\xff\xff"

    def test_ip_checksum_is_valid(self):
        """Summing a header that includes a correct checksum gives 0xFFFF."""
        ip = build_discover(XID, MAC)[14:34]
        total = sum(struct.unpack("!10H", ip))
        while total > 0xFFFF:
            total = (total & 0xFFFF) + (total >> 16)
        assert total == 0xFFFF
        assert ip[10:12] != b"\x00\x00"

    def test_udp_header(self):
        frame = build_discover(XID, MAC)
        sport, dport, length, _ = struct.unpack("!HHHH", frame[34:42])
        assert (sport, dport) == (68, 67)
        assert length == len(frame) - 34

    def test_bootp_fields(self):
        bootp = build_discover(XID, MAC)[42:]
        assert bootp[0:4] == bytes([1, 1, 6, 0])  # BOOTREQUEST, Ethernet, hlen 6
        assert struct.unpack("!I", bootp[4:8])[0] == XID
        assert struct.unpack("!H", bootp[10:12])[0] == 0x8000  # broadcast flag
        assert bootp[28:34] == MAC
        assert bootp[34:44] == b"\x00" * 10
        assert bootp[236:240] == b"\x63\x82\x53\x63"
        assert len(bootp) >= 300

    def test_options(self):
        options = build_discover(XID, MAC)[42 + 240 :]
        assert options[0:3] == bytes([53, 1, 1])  # DHCPDISCOVER
        assert options[3:9] == bytes([55, 4, 1, 3, 6, 54])
        assert options[9] == 255
        assert set(options[10:]) <= {0}  # padding only

    @pytest.mark.parametrize("xid", [-1, 2**32])
    def test_rejects_bad_xid(self, xid):
        with pytest.raises(ValueError):
            build_discover(xid, MAC)

    def test_rejects_bad_mac(self):
        with pytest.raises(ValueError):
            build_discover(XID, b"\x00" * 5)


class TestParseOffer:
    def test_parses_offer(self):
        assert parse_offer(make_offer(), XID) == {
            "server_ip": "192.168.1.1",
            "offered_ip": "192.168.1.77",
        }

    def test_server_id_option_wins_over_ip_source(self):
        frame = make_offer(server_id="192.168.1.2", src_ip="192.168.1.254")
        assert parse_offer(frame, XID)["server_ip"] == "192.168.1.2"

    def test_falls_back_to_ip_source_without_option_54(self):
        frame = make_offer(server_id=None, src_ip="192.168.1.254")
        assert parse_offer(frame, XID)["server_ip"] == "192.168.1.254"

    def test_handles_ip_options(self):
        assert parse_offer(make_offer(ihl=6), XID) is not None

    def test_skips_pad_options(self):
        frame = make_offer(extra_options=b"\x00\x00\x00")
        assert parse_offer(frame, XID) is not None

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"xid": XID + 1},
            {"msg_type": 5},  # ACK
            {"msg_type": 1},  # DISCOVER
            {"op": 1},
            {"sport": 68, "dport": 67},  # our own DISCOVER looping back
            {"sport": 53},
            {"ethertype": 0x86DD},
        ],
    )
    def test_rejects_non_matching(self, kwargs):
        assert parse_offer(make_offer(**kwargs), XID) is None

    def test_rejects_our_own_discover(self):
        assert parse_offer(build_discover(XID, MAC), XID) is None

    @pytest.mark.parametrize("cut", [0, 13, 33, 41, 100, 270, 281])
    def test_rejects_truncated_frames(self, cut):
        assert parse_offer(make_offer()[:cut], XID) is None

    def test_rejects_bad_magic_cookie(self):
        frame = bytearray(make_offer())
        frame[14 + 20 + 8 + 236] = 0
        assert parse_offer(bytes(frame), XID) is None

    def test_truncated_option_does_not_crash(self):
        frame = make_offer(server_id=None)[:-1] + bytes([54, 4, 192])  # cut value
        assert parse_offer(frame, XID)["server_ip"] == "192.168.1.1"

    def test_rejects_non_ipv4_and_non_udp(self):
        frame = bytearray(make_offer())
        frame[14 + 9] = 6  # TCP
        assert parse_offer(bytes(frame), XID) is None
        frame = bytearray(make_offer())
        frame[14] = 0x65  # version 6
        assert parse_offer(bytes(frame), XID) is None


class _FakeSocket:
    """Socket double: returns queued frames, then times out."""

    def __init__(self, frames):
        self.frames = list(frames)
        self.sent = []
        self.bound = None
        self.closed = False
        self.timeouts = []

    def bind(self, addr):
        self.bound = addr

    def send(self, data):
        self.sent.append(data)
        return len(data)

    def settimeout(self, value):
        self.timeouts.append(value)

    def recv(self, _size):
        if not self.frames:
            raise socket.timeout()
        return self.frames.pop(0)

    def close(self):
        self.closed = True


def _socket_module(factory):
    """Stand-in for the probe module's ``socket`` global only.

    Patching socket.socket itself would also break asyncio's own self-pipe.
    """
    return types.SimpleNamespace(
        socket=factory,
        SOCK_RAW=socket.SOCK_RAW,
        htons=socket.htons,
        timeout=socket.timeout,
    )


class TestProbeDhcpServers:
    def _run(self, frames, xid=XID, **kwargs):
        fake = _FakeSocket(frames)
        factory = MagicMock(return_value=fake)
        with (
            patch.object(dhcp_probe, "socket", _socket_module(factory)),
            patch.object(dhcp_probe.secrets, "randbits", return_value=xid),
        ):
            result = asyncio.run(
                probe_dhcp_servers("enp1s0", "aa:bb:cc:dd:ee:ff", **kwargs)
            )
        return result, fake, factory

    def test_collects_and_dedupes_servers(self):
        frames = [
            build_discover(XID, MAC),  # our own frame looped back
            make_offer(server_id="192.168.1.1", offered="192.168.1.77"),
            make_offer(server_id="192.168.1.1", offered="192.168.1.78"),
            make_offer(server_id="192.168.1.2", offered="192.168.1.90"),
            make_offer(xid=XID + 1, server_id="192.168.1.3"),
        ]
        result, fake, factory = self._run(frames)
        assert result == [
            {"server_ip": "192.168.1.1", "offered_ip": "192.168.1.77"},
            {"server_ip": "192.168.1.2", "offered_ip": "192.168.1.90"},
        ]
        assert fake.bound == ("enp1s0", 0x0800)
        assert fake.sent == [build_discover(XID, MAC)]
        assert fake.closed
        family, kind, proto = factory.call_args.args
        assert family == dhcp_probe._AF_PACKET
        assert kind == socket.SOCK_RAW
        assert proto == socket.htons(0x0800)

    def test_no_answer_returns_empty(self):
        result, fake, _ = self._run([])
        assert result == []
        assert fake.closed

    def test_timeout_shrinks_toward_deadline(self):
        _, fake, _ = self._run([make_offer()], timeout=0.5)
        assert all(0 < t <= 0.5 for t in fake.timeouts)

    def test_closes_socket_on_error(self):
        fake = _FakeSocket([])
        fake.bind = MagicMock(side_effect=OSError(19, "No such device"))
        factory = MagicMock(return_value=fake)
        with patch.object(dhcp_probe, "socket", _socket_module(factory)):
            with pytest.raises(OSError):
                asyncio.run(probe_dhcp_servers("enp1s0", "aa:bb:cc:dd:ee:ff"))
        assert fake.closed

    def test_permission_error_propagates(self):
        """No NET_RAW must surface as an error, never as 'no other server'."""
        factory = MagicMock(side_effect=PermissionError(1, "x"))
        with patch.object(dhcp_probe, "socket", _socket_module(factory)):
            with pytest.raises(PermissionError):
                asyncio.run(probe_dhcp_servers("enp1s0", "aa:bb:cc:dd:ee:ff"))

    @pytest.mark.parametrize(
        "iface, mac",
        [
            ("bad iface", "aa:bb:cc:dd:ee:ff"),
            ("enp1s0", "aabbccddeeff"),
            ("enp1s0", ""),
        ],
    )
    def test_validates_inputs_before_opening_socket(self, iface, mac):
        factory = MagicMock()
        with patch.object(dhcp_probe, "socket", _socket_module(factory)):
            with pytest.raises(ValueError):
                asyncio.run(probe_dhcp_servers(iface, mac))
        factory.assert_not_called()
