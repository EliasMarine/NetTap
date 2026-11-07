"""Synthetic capture for NetTap packet-analysis tests: documentation addresses only."""

import struct
import sys


def csum(b):
    if len(b) % 2:
        b += b"\0"
    s = sum(struct.unpack("!%dH" % (len(b) // 2), b))
    while s >> 16:
        s = (s & 0xFFFF) + (s >> 16)
    return (~s) & 0xFFFF


def eth(dst, src, body, etype=0x0800):
    return (
        bytes.fromhex(dst.replace(":", ""))
        + bytes.fromhex(src.replace(":", ""))
        + struct.pack("!H", etype)
        + body
    )


def ipv4(src, dst, proto, payload, ident=1):
    hdr = struct.pack(
        "!BBHHHBBH4s4s",
        0x45,
        0,
        20 + len(payload),
        ident,
        0x4000,
        64,
        proto,
        0,
        bytes(map(int, src.split("."))),
        bytes(map(int, dst.split("."))),
    )
    hdr = hdr[:10] + struct.pack("!H", csum(hdr)) + hdr[12:]
    return hdr + payload


def tcp(sp, dp, seq, ack, flags, data=b""):
    return (
        struct.pack("!HHIIBBHHH", sp, dp, seq, ack, 5 << 4, flags, 64240, 0, 0) + data
    )


def udp(sp, dp, data):
    return struct.pack("!HHHH", sp, dp, 8 + len(data), 0) + data


def dns_reply():
    q = b"\x07example\x03com\x00" + struct.pack("!HH", 1, 1)
    hdr = struct.pack("!HHHHHH", 0x1234, 0x8180, 1, 2, 0, 0)
    ans = b"".join(
        b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 60, 4) + bytes([192, 0, 2, x])
        for x in (80, 81)
    )
    return hdr + q + ans


C, S, D = "02:00:00:00:00:01", "02:00:00:00:00:02", "02:00:00:00:00:03"
T0 = 1700000000
pkts = []  # (sec, usec, frame bytes, orig_len)
syn = eth(
    S, C, ipv4("192.0.2.10", "198.51.100.20", 6, tcp(50000, 443, 1000, 0, 0x02), 1)
)
synack = eth(
    C, S, ipv4("198.51.100.20", "192.0.2.10", 6, tcp(443, 50000, 5000, 1001, 0x12), 2)
)
ack = eth(
    S, C, ipv4("192.0.2.10", "198.51.100.20", 6, tcp(50000, 443, 1001, 5001, 0x10), 3)
)
dns = eth(C, D, ipv4("198.51.100.53", "192.0.2.10", 17, udp(53, 50001, dns_reply()), 4))
big = eth(
    S,
    C,
    ipv4(
        "192.0.2.10",
        "198.51.100.20",
        6,
        tcp(50000, 443, 1001, 5001, 0x18, b"\x00" * 1460),
        5,
    ),
)
http = eth(
    S,
    C,
    ipv4(
        "192.0.2.10",
        "198.51.100.30",
        6,
        tcp(50002, 80, 1, 1, 0x18, b"GET /a\tb HTTP/1.1\r\nHost: example.com\r\n\r\n"),
        6,
    ),
)
pkts.append((T0, 1, syn, len(syn)))
pkts.append((T0, 1, synack, len(synack)))  # same time, different bytes
pkts.append((T0, 250001, ack, len(ack)))
pkts.append((T0, 500001, dns, len(dns)))
pkts.append((T0, 750001, big[:96], len(big)))  # truncated by snaplen
pkts.append((T0 + 1, 1, http, len(http)))
out = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
for sec, usec, data, orig in pkts:
    out += struct.pack("<IIII", sec, usec, len(data), orig) + data
if __name__ == "__main__":
    sys.stdout.buffer.write(out)
