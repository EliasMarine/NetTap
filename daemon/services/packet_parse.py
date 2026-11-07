"""Parsing and checking what TShark returns for packet analysis (NET-188).

Pure functions, no I/O: the field rows of a search, one packet's PDML tree and
hex dump, and the pcap stream of a download, verified record by record.
"""

from __future__ import annotations

import hashlib
import re
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from io import BytesIO

# Every field below exists in TShark 4.0.17 (checked on the G11, 2026-11-07).
IDENTITY_FIELDS = (
    "frame.number",
    "frame.time_epoch",
    "frame.len",
    "frame.cap_len",
    "frame.md5_hash",
)
DETAIL_FIELDS = (
    "eth.src", "eth.dst",
    "ip.src", "ip.dst", "ipv6.src", "ipv6.dst", "ip.proto", "ip.ttl",
    "tcp.srcport", "tcp.dstport", "tcp.stream", "tcp.flags", "tcp.len", "tcp.seq",
    "tcp.ack", "tcp.window_size", "tcp.analysis.initial_rtt",
    "udp.srcport", "udp.dstport", "udp.stream",
    "_ws.expert.message", "_ws.expert.severity", "_ws.expert.group",
    "tls.handshake.type", "tls.handshake.extensions_server_name",
    "tls.handshake.version", "tls.alert_message.desc",
    "dns.id", "dns.flags.response", "dns.flags.rcode", "dns.qry.name", "dns.qry.type",
    "dns.a", "dns.aaaa", "dns.cname", "dns.count.answers", "dns.time",
    "http.request.method", "http.request.uri", "http.host", "http.response.code",
    "http.response.phrase", "http.time",
    "icmp.type", "icmp.code", "icmpv6.type", "icmpv6.code",
    "dhcp.option.dhcp", "dhcp.option.hostname", "dhcp.option.requested_ip_address",
    "dhcp.ip.your", "dhcp.hw.mac_addr",
    "arp.opcode", "arp.src.proto_ipv4", "arp.dst.proto_ipv4", "arp.src.hw_mac",
    "quic.long.packet_type", "quic.version",
)  # fmt: skip
COLUMN_FIELDS = ("_ws.col.Protocol", "_ws.col.Info")  # Info last: it may hold tabs
ALL_FIELDS = IDENTITY_FIELDS + DETAIL_FIELDS + COLUMN_FIELDS
AGGREGATOR = "\x1f"  # joins repeated values (every answer of a DNS reply)

EPOCH = re.compile(r"^\d{1,12}(\.\d{1,9})?$")
MD5 = re.compile(r"^[0-9a-f]{32}$")


class ParseError(Exception):
    """TShark's output wasn't in the shape asked for: a failure, never data."""


@dataclass(frozen=True)
class Frame:
    """A packet's identity: its number in the window and its captured bytes."""

    n: int
    t: str
    cap_len: int
    md5: str


def epoch_ns(value: str) -> int:
    """'1794026064.094483' to nanoseconds, exactly."""
    if not EPOCH.match(value):
        raise ValueError(f"not an epoch time: {value!r}")
    whole, _, frac = value.partition(".")
    return int(whole) * 1_000_000_000 + int(frac.ljust(9, "0"))


def ns_epoch(ns: int) -> str:
    """Nanoseconds to TShark's epoch format, 9 decimals."""
    return f"{ns // 1_000_000_000}.{ns % 1_000_000_000:09d}"


# --- search rows ------------------------------------------------------------


def parse_rows(stdout: bytes, *, partial_tail_ok: bool) -> list[dict]:
    """TShark's tab-separated field rows to packet dicts.

    A row with the wrong number of columns is an error, never skipped. An
    unterminated last row is dropped only when the job was stopped mid-write.
    """
    text = stdout.decode("utf-8", errors="replace")
    lines = text.split("\n")
    tail = lines.pop()
    if tail and not partial_tail_ok:
        raise ParseError("TShark's output ended in the middle of a row")
    rows = []
    for line in lines:
        cols = line.split("\t", len(ALL_FIELDS) - 1)
        if len(cols) != len(ALL_FIELDS):
            raise ParseError(f"a row had {len(cols)} columns, not {len(ALL_FIELDS)}")
        rows.append(_row(cols))
    for a, b in zip(rows, rows[1:]):
        if b["n"] <= a["n"]:
            raise ParseError("frame numbers out of order")
    return rows


def _row(cols: list[str]) -> dict:
    n, t, length, cap_len, md5 = cols[: len(IDENTITY_FIELDS)]
    if not (n.isdigit() and length.isdigit() and cap_len.isdigit() and MD5.match(md5)):
        raise ParseError(f"unreadable packet identity: {cols[:5]}")
    epoch_ns(t)  # validates
    detail = cols[len(IDENTITY_FIELDS) : len(IDENTITY_FIELDS) + len(DETAIL_FIELDS)]
    fields = {
        name: value.split(AGGREGATOR)
        for name, value in zip(DETAIL_FIELDS, detail)
        if value != ""
    }
    return {
        "n": int(n),
        "t": t,
        "len": int(length),
        "cap_len": int(cap_len),
        "md5": md5,
        "protocol": cols[-2],
        "info": cols[-1],
        "fields": fields,
    }


# --- one packet: PDML and hex ---------------------------------------------

PDML_MAX_BYTES = 2 * 1024 * 1024
PDML_MAX_NODES = 4000
PDML_MAX_DEPTH = 32
MARKABLE = ("eth", "vlan", "arp", "ip", "ipv6", "tcp", "udp", "icmp", "icmpv6")
_REASSEMBLY = {
    "ip.reassembled_in", "ip.fragments", "ipv6.fragments", "ipv6.reassembled_in",
    "tcp.segments", "tcp.reassembled_in", "tls.segments",
}  # fmt: skip


def _int_attr(el: ET.Element, name: str) -> int | None:
    raw = el.get(name)
    return int(raw) if raw is not None and raw.isdigit() else None


def parse_pdml(data: bytes) -> list[dict]:
    """One packet's PDML to a tree of {kind, name, showname, show, value, pos, size}.

    Caps on size, node count and depth make an oversized tree an error.
    """
    if len(data) > PDML_MAX_BYTES:
        raise ParseError("the packet's detail is larger than 2 MB")
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise ParseError("unexpected DTD in PDML")
    packets = 0
    nodes = 0
    stack: list[dict] = []
    layers: list[dict] = []
    try:
        for event, el in ET.iterparse(BytesIO(data), events=("start", "end")):
            if el.tag == "packet":
                packets += event == "start"
                continue
            if el.tag not in ("proto", "field"):
                continue
            if event == "end":
                stack.pop()
                el.clear()
                continue
            nodes += 1
            if nodes > PDML_MAX_NODES or len(stack) >= PDML_MAX_DEPTH:
                raise ParseError("the packet's detail tree is too large")
            node = {
                "kind": el.tag,
                "name": el.get("name", ""),
                "showname": el.get("showname", ""),
                "show": el.get("show", ""),
                "value": el.get("unmaskedvalue") or el.get("value") or "",
                "pos": _int_attr(el, "pos"),
                "size": _int_attr(el, "size"),
                "hide": el.get("hide") == "yes",
                "children": [],
            }
            (stack[-1]["children"] if stack else layers).append(node)
            stack.append(node)
    except ET.ParseError as exc:
        raise ParseError(f"PDML didn't parse: {exc}") from exc
    if packets != 1:
        raise ParseError(f"expected one packet in PDML, got {packets}")
    return [layer for layer in layers if layer["name"] != "geninfo"]


def _walk(nodes: list[dict]):
    for node in nodes:
        yield node
        yield from _walk(node["children"])


def pdml_identity(layers: list[dict]) -> tuple[str, int, int, str]:
    """(time, captured length, length on the wire, MD5) from the frame layer."""
    found = {
        n["name"]: n["show"]
        for n in _walk(layers)
        if n["name"]
        in ("frame.time_epoch", "frame.cap_len", "frame.len", "frame.md5_hash")
    }
    try:
        return (
            found["frame.time_epoch"],
            int(found["frame.cap_len"]),
            int(found["frame.len"]),
            found["frame.md5_hash"],
        )
    except (KeyError, ValueError) as exc:
        raise ParseError(f"the frame layer lacks {exc}") from exc


def mark_bytes(layers: list[dict], frame: bytes) -> str:
    """Give each field a `mark` [pos, size] only where it is proven against the bytes.

    Returns "headers" when the header chain could be checked, or "none" when the
    packet shows reassembly or other transformed data, which marks nothing.
    Proven means: the field sits in a protocol on the contiguous header chain from
    eth, inside that protocol's range, and its value equals the frame's bytes there.
    """
    for layer in layers:
        layer["markable"] = False
        for node in _walk([layer]):
            node["mark"] = None
    names = {n["name"] for n in _walk(layers)}
    if names & _REASSEMBLY or any(".reassembled" in name for name in names):
        return "none"
    expected_pos = 0
    for layer in layers:
        if layer["name"] == "frame":
            continue
        pos, size = layer["pos"], layer["size"]
        if layer["name"] not in MARKABLE or pos != expected_pos or not size:
            break
        if layer["name"] != "eth" and expected_pos == 0:
            break
        layer["markable"] = True
        for node in _walk(layer["children"]):
            _mark_field(node, pos, pos + size, frame)
        expected_pos = pos + size
    return "headers"


def _mark_field(node: dict, lo: int, hi: int, frame: bytes) -> None:
    pos, size, value = node["pos"], node["size"], node["value"].lower()
    if pos is None or not size or not value or pos < lo or pos + size > hi:
        return
    if frame[pos : pos + size].hex() == value:
        node["mark"] = [pos, size]


_HEX_LINE = re.compile(r"^([0-9a-f]{4,8})  ((?:[0-9a-f]{2} ?)+)\s*$")


def parse_hex(text: str) -> bytes:
    """TShark's `-x --hexdump frames --hexdump noascii` dump back to bytes."""
    out = bytearray()
    for line in text.splitlines():
        m = _HEX_LINE.match(line)
        if not m:
            continue
        if int(m.group(1), 16) != len(out):
            raise ParseError("the hex dump skipped bytes")
        out += bytes.fromhex(m.group(2).replace(" ", ""))
    if not out:
        raise ParseError("no hex dump came back")
    return bytes(out)


# --- download: the pcap stream, verified record by record --------------------

_MAGIC = {
    b"\x4d\x3c\xb2\xa1": ("<", 1),  # nanosecond, little-endian
    b"\xa1\xb2\x3c\x4d": (">", 1),
    b"\xd4\xc3\xb2\xa1": ("<", 1000),  # microsecond
    b"\xa1\xb2\xc3\xd4": (">", 1000),
}
_MAX_RECORD = 16 * 1024 * 1024


class StreamMismatch(Exception):
    """A record in the download differs from the packet the search showed."""


class PcapVerifier:
    """Feed it the stream; it hands back only bytes whose records were verified."""

    def __init__(self, frames: list[Frame]) -> None:
        self._frames = frames
        self._buf = bytearray()
        self._order: str | None = None
        self._scale = 1
        self._header = b""
        self.verified = 0

    def feed(self, chunk: bytes) -> bytes:
        self._buf += chunk
        out = bytearray()
        if self._order is None:
            if len(self._buf) < 24:
                return b""
            magic = bytes(self._buf[:4])
            if magic not in _MAGIC:
                raise StreamMismatch("the download isn't a pcap stream")
            self._order, self._scale = _MAGIC[magic]
            self._header = bytes(self._buf[:24])
            del self._buf[:24]
        while len(self._buf) >= 16:
            sec, frac, incl, _orig = struct.unpack(self._order + "IIII", self._buf[:16])
            if incl > _MAX_RECORD:
                raise StreamMismatch("a record is larger than any packet")
            if len(self._buf) < 16 + incl:
                break
            record = bytes(self._buf[: 16 + incl])
            self._check(sec * 1_000_000_000 + frac * self._scale, incl, record[16:])
            del self._buf[: 16 + incl]
            if self.verified == 1:
                out += self._header
            out += record
        return bytes(out)

    def _check(self, ts_ns: int, incl: int, data: bytes) -> None:
        k = self.verified
        if k >= len(self._frames):
            raise StreamMismatch("the download has more packets than the search")
        want = self._frames[k]
        if (
            ts_ns != epoch_ns(want.t)
            or incl != want.cap_len
            or hashlib.md5(data, usedforsecurity=False).hexdigest() != want.md5
        ):
            raise StreamMismatch(f"packet {want.n} differs from the search")
        self.verified += 1

    def finish(self) -> None:
        if self._buf:
            raise StreamMismatch("the download ended in the middle of a packet")
        if self.verified != len(self._frames):
            raise StreamMismatch(
                f"the download had {self.verified} of {len(self._frames)} packets"
            )
