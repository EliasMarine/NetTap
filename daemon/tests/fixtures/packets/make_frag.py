"""Two IPv4 fragments (documentation addresses). The reassembled TCP source port is 80
(bytes 00 50), the same bytes the destination MAC starts with."""
import struct, sys
sys.path.insert(0, sys.argv[1])
from make_pcap import csum, eth
def frag(ident, mf, off8, payload):
    hdr = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(payload), ident, (0x2000 if mf else 0) | off8, 64, 6, 0,
                      bytes([192, 0, 2, 10]), bytes([203, 0, 113, 45]))
    return hdr[:10] + struct.pack("!H", csum(hdr)) + hdr[12:] + payload
seg = struct.pack("!HHIIBBHHH", 80, 50000, 1, 1, 5 << 4, 0x18, 64240, 0, 0) + b"HTTP/1.1 200 OK\r\n\r\n."
f1 = eth("00:50:56:aa:bb:cc", "02:00:00:00:00:01", frag(0x4242, True, 0, seg[:16]))
f2 = eth("00:50:56:aa:bb:cc", "02:00:00:00:00:01", frag(0x4242, False, 2, seg[16:]))
out = struct.pack("<IHHiIII", 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1)
for i, d in enumerate((f1, f2)):
    out += struct.pack("<IIII", 1700000100, 1 + i, len(d), len(d)) + d
sys.stdout.buffer.write(out)
