"""Parsing TShark's output for packet analysis (NET-188), on outputs recorded on the G11."""

import hashlib
import struct
from pathlib import Path

import pytest

from services.packet_parse import (
    ALL_FIELDS,
    Frame,
    ParseError,
    PcapVerifier,
    StreamMismatch,
    epoch_ns,
    mark_bytes,
    ns_epoch,
    parse_hex,
    parse_pdml,
    parse_rows,
    pdml_identity,
)

FIX = Path(__file__).parent / "fixtures" / "packets"


def _detail(name: str) -> tuple[list[dict], bytes]:
    pdml, _, hexdump = (FIX / name).read_bytes().partition(b"\n#nt-hex\n")
    return parse_pdml(pdml), parse_hex(hexdump.decode())


def _walk(nodes):
    for n in nodes:
        yield n
        yield from _walk(n["children"])


class TestRows:
    def test_real_rows(self):
        rows = parse_rows((FIX / "search_all.out").read_bytes(), partial_tail_ok=False)
        assert [r["n"] for r in rows] == [1, 2, 3, 4, 5, 6]
        # same microsecond, told apart by their bytes
        assert rows[0]["t"] == rows[1]["t"] and rows[0]["md5"] != rows[1]["md5"]
        assert rows[3]["fields"]["dns.a"] == ["192.0.2.80", "192.0.2.81"]
        assert (rows[4]["len"], rows[4]["cap_len"]) == (1514, 96)
        assert rows[5]["fields"]["http.request.uri"] == [
            "/a\\tb"
        ]  # TShark 4.0 escapes tabs
        assert "tcp.srcport" not in rows[3]["fields"]  # empty fields are left out

    def test_wrong_column_count_is_an_error(self):
        with pytest.raises(ParseError):
            parse_rows(b"1\t2\t3\n", partial_tail_ok=False)

    def test_unterminated_row_only_after_a_stop(self):
        data = (FIX / "search_all.out").read_bytes()
        cut = data[: data.rindex(b"\n", 0, len(data) - 1) + 20]
        with pytest.raises(ParseError):
            parse_rows(cut, partial_tail_ok=False)
        assert len(parse_rows(cut, partial_tail_ok=True)) == 5

    def test_a_tab_inside_info_stays_in_info(self):
        cols = ["1", "1.5", "60", "60", "a" * 32] + [""] * (len(ALL_FIELDS) - 7)
        line = "\t".join(cols + ["TCP", "left\tright"]) + "\n"
        assert (
            parse_rows(line.encode(), partial_tail_ok=False)[0]["info"] == "left\tright"
        )

    def test_frame_numbers_must_increase(self):
        lines = (FIX / "search_all.out").read_bytes().split(b"\n")
        with pytest.raises(ParseError):
            parse_rows(lines[1] + b"\n" + lines[0] + b"\n", partial_tail_ok=False)


class TestEpoch:
    def test_exact_round_trip(self):
        assert epoch_ns("1700000000.000001") == 1_700_000_000_000_001_000
        assert ns_epoch(1_700_000_000_000_001_000) == "1700000000.000001000"
        assert epoch_ns("1700000000") == 1_700_000_000 * 10**9

    @pytest.mark.parametrize("bad", ["", "1e9", "-1", "1.0000000001", "1.", " 1"])
    def test_refuses(self, bad):
        with pytest.raises(ValueError):
            epoch_ns(bad)


class TestDetail:
    def test_identity_and_bytes_agree(self):
        layers, frame = _detail("detail_1.out")
        t, cap_len, length, md5 = pdml_identity(layers)
        assert (t, cap_len, length) == ("1700000000.000001000", 54, 54)
        assert hashlib.md5(frame).hexdigest() == md5 and len(frame) == 54

    def test_headers_marked_where_bytes_prove_it(self):
        layers, frame = _detail("detail_1.out")
        assert mark_bytes(layers, frame) == "headers"
        by_name = {n["name"]: n for n in _walk(layers)}
        assert by_name["ip.src"]["mark"] == [26, 4]
        assert by_name["tcp.dstport"]["mark"] == [36, 2]
        assert [layer["markable"] for layer in layers] == [False, True, True, True]

    def test_truncated_packet_uses_captured_length(self):
        layers, frame = _detail("detail_5.out")
        t, cap_len, length, md5 = pdml_identity(layers)
        assert (cap_len, length, len(frame)) == (96, 1514, 96)
        assert hashlib.md5(frame).hexdigest() == md5
        mark_bytes(layers, frame)
        tls = next(layer for layer in layers if layer["name"] == "tls")
        assert not tls["markable"]  # not on the header whitelist
        payload = next(n for n in _walk(layers) if n["name"] == "tcp.payload")
        assert payload["mark"] is None  # outside the tcp header's range

    def test_reassembled_packet_marks_nothing(self):
        # The reassembled tcp.srcport is 0050 at pos 0 of the reassembled buffer, and
        # the frame's first bytes are 00 50 (the destination MAC): a coincidence.
        layers, frame = _detail("detail_frag.out")
        srcport = next(n for n in _walk(layers) if n["name"] == "tcp.srcport")
        assert (srcport["pos"], srcport["value"], frame[:2].hex()) == (
            0,
            "0050",
            "0050",
        )
        assert mark_bytes(layers, frame) == "none"
        assert all(n.get("mark") is None for n in _walk(layers))

    def test_mismatching_value_is_not_marked(self):
        layers, frame = _detail("detail_1.out")
        changed = bytearray(frame)
        changed[26] ^= 0xFF  # first byte of ip.src
        mark_bytes(layers, bytes(changed))
        by_name = {n["name"]: n for n in _walk(layers)}
        assert by_name["ip.src"]["mark"] is None
        assert by_name["ip.dst"]["mark"] == [30, 4]

    def test_caps(self, monkeypatch):
        pdml = (FIX / "detail_1.out").read_bytes().partition(b"\n#nt-hex\n")[0]
        monkeypatch.setattr("services.packet_parse.PDML_MAX_NODES", 10)
        with pytest.raises(ParseError):
            parse_pdml(pdml)
        monkeypatch.setattr("services.packet_parse.PDML_MAX_NODES", 4000)
        monkeypatch.setattr("services.packet_parse.PDML_MAX_DEPTH", 2)
        with pytest.raises(ParseError):
            parse_pdml(pdml)
        with pytest.raises(ParseError):
            parse_pdml(b"<!DOCTYPE x [<!ENTITY a 'b'>]>" + pdml)

    def test_two_packets_is_an_error(self):
        pdml = (FIX / "detail_1.out").read_bytes().partition(b"\n#nt-hex\n")[0]
        packet = pdml[pdml.index(b"<packet>") : pdml.index(b"</packet>") + 9]
        with pytest.raises(ParseError):
            parse_pdml(pdml.replace(packet, packet + packet))

    def test_hex_with_a_gap_is_an_error(self):
        with pytest.raises(ParseError):
            parse_hex("0000  00 01\n0020  02 03\n")
        with pytest.raises(ParseError):
            parse_hex("nothing here\n")


def _frames() -> list[Frame]:
    rows = parse_rows((FIX / "search_all.out").read_bytes(), partial_tail_ok=False)
    return [
        Frame(r["n"], r["t"], r["cap_len"], r["md5"])
        for r in rows
        if r["n"] in (1, 2, 5)
    ]


class TestPcapVerifier:
    def test_real_download_verifies(self):
        v = PcapVerifier(_frames())
        data = (FIX / "download_125.out").read_bytes()
        out = b"".join(v.feed(data[i : i + 7]) for i in range(0, len(data), 7))
        v.finish()
        assert out == data and v.verified == 3

    def test_nothing_is_released_before_a_record_is_verified(self):
        v = PcapVerifier(_frames())
        data = (FIX / "download_125.out").read_bytes()
        assert v.feed(data[: 24 + 16 + 10]) == b""

    def test_changed_bytes_abort(self):
        data = bytearray((FIX / "download_125.out").read_bytes())
        data[-1] ^= 1
        v = PcapVerifier(_frames())
        with pytest.raises(StreamMismatch):
            v.feed(bytes(data))

    def test_changed_time_aborts(self):
        data = bytearray((FIX / "download_125.out").read_bytes())
        sec, frac = struct.unpack("<II", data[24:32])
        data[28:32] = struct.pack("<I", frac + 1)
        with pytest.raises(StreamMismatch):
            PcapVerifier(_frames()).feed(bytes(data))

    def test_short_count_fails_at_the_end(self):
        frames = _frames()
        v = PcapVerifier(frames + [Frame(6, "1700000001.000001", 94, "0" * 32)])
        v.feed((FIX / "download_125.out").read_bytes())
        with pytest.raises(StreamMismatch):
            v.finish()

    def test_extra_record_aborts(self):
        v = PcapVerifier(_frames()[:2])
        with pytest.raises(StreamMismatch):
            v.feed((FIX / "download_125.out").read_bytes())

    def test_not_pcap(self):
        with pytest.raises(StreamMismatch):
            PcapVerifier(_frames()).feed(b"x" * 40)
