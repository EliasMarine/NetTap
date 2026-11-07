"""The PCAP writer, fixtures and report behind scripts/remote/verify_detection.py (NET-191 replay)."""

import importlib.util
import ipaddress
import json
import struct
from pathlib import Path

_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "remote" / "verify_detection.py"
)
_spec = importlib.util.spec_from_file_location("verify_detection", _PATH)
vd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vd)

HOME_NET = [
    ipaddress.ip_network(n) for n in ("192.168.0.0/16", "10.0.0.0/8", "172.16.0.0/12")
]


def _in_home(ip: str) -> bool:
    return any(ipaddress.ip_address(ip) in net for net in HOME_NET)


def _read_pcap(path: Path) -> list:
    data = path.read_bytes()
    magic, major, minor, _, _, snaplen, linktype = struct.unpack("<IHHiIII", data[:24])
    assert (magic, major, minor, snaplen, linktype) == (0xA1B2C3D4, 2, 4, 65535, 1)
    frames, offset = [], 24
    while offset < len(data):
        _, _, incl, orig = struct.unpack("<IIII", data[offset : offset + 16])
        assert incl == orig
        frames.append(data[offset + 16 : offset + 16 + incl])
        offset += 16 + incl
    assert offset == len(data)
    return frames


def _udp_payload(frame: bytes) -> bytes:
    return frame[14 + 20 + 8 :]


def _fixture(name: str) -> dict:
    return next(f for f in vd.FIXTURES if f["name"] == name)


# --- packets -------------------------------------------------------------------------------


def test_frame_is_ethernet_ipv4_udp_with_a_valid_header_checksum():
    frame = vd.udp_frame("192.168.1.44", 50001, "192.0.2.53", 53, b"abc")
    assert frame[12:14] == b"\x08\x00"
    ip = frame[14:34]
    assert ip[0] == 0x45 and ip[9] == 17
    assert vd.ipv4_checksum(ip) == 0  # a correct checksum sums to 0xFFFF, complement 0
    assert struct.unpack("!H", ip[2:4])[0] == 20 + 8 + 3
    assert ipaddress.IPv4Address(ip[12:16]) == ipaddress.IPv4Address("192.168.1.44")
    sport, dport, length, _ = struct.unpack("!HHHH", frame[34:42])
    assert (sport, dport, length) == (50001, 53, 11)
    assert _udp_payload(frame) == b"abc"


def test_dns_query_encodes_labels_and_rejects_an_oversized_label():
    payload = vd.dns_query("node1.mysterium.network", 0x4401)
    assert payload[:12] == struct.pack("!HHHHHH", 0x4401, 0x0100, 1, 0, 0, 0)
    assert payload[12:] == b"\x05node1\x09mysterium\x07network\x00\x00\x01\x00\x01"
    try:
        vd.dns_query("x" * 64 + ".example", 1)
    except AssertionError:
        return
    raise AssertionError(
        "a 64-byte label must be refused (it would read as a compression pointer)"
    )


def test_fixture_pcaps_are_identical_on_every_run(tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    vd.write_fixtures(str(first))
    vd.write_fixtures(str(second))
    names = sorted(p.name for p in first.iterdir())
    assert names == sorted(f"{f['name']}.pcap" for f in vd.FIXTURES)
    for name in names:
        assert (first / name).read_bytes() == (second / name).read_bytes()
        assert _read_pcap(first / name)


# --- fixtures match the rules they target --------------------------------------------------


def test_stun_fixture_matches_2033078():
    # udp $HOME_NET any -> $EXTERNAL_NET [!3478,1023:]; |00 01| depth 2; |21 12 a4 42| at 4
    src, _, dst, dport, payload = _fixture("activity-stun")["packets"][0]
    assert _in_home(src) and not _in_home(dst)
    assert dport >= 1023 and dport != 3478
    assert payload[:2] == b"\x00\x01" and payload[4:8] == bytes.fromhex("2112a442")


def test_large_dns_fixture_matches_2013075():
    # udp $HOME_NET any -> any 53; |01 00 00 01 00 00 00 00 00 00| at offset 2; dsize:>300
    src, _, _, dport, payload = _fixture("keep-2013075-44")["packets"][0]
    assert src == vd.SUPPRESSED_DEVICE and dport == 53
    assert payload[2:12] == bytes.fromhex("01000001000000000000")
    assert len(payload) > 300
    for excluded in (
        b"youtube\x03com\x00",
        b"sophosxl\x03net\x00",
        b"spamhaus\x03org\x00",
    ):
        assert excluded not in payload


def test_suppression_fixture_sends_the_same_mysterium_query_from_44_and_99():
    packets = _fixture("suppress-44")["packets"]
    assert [p[0] for p in packets] == [vd.SUPPRESSED_DEVICE, vd.OTHER_DEVICE]
    for _, _, _, dport, payload in packets:
        assert dport == 53
        # dns.query; dotprefix; content:".mysterium.network"; endswith
        assert b"\x09mysterium\x07network\x00" in payload


# --- assertions ----------------------------------------------------------------------------


def test_check_fixture_pass_fail_and_skip():
    suppress = _fixture("suppress-44")
    met = {"threshold": (True, "")}
    ok = {(2067457, vd.OTHER_DEVICE)}
    assert vd.check_fixture(suppress, ok, met) == ("PASS", "")

    leaked = ok | {(2067457, vd.SUPPRESSED_DEVICE)}
    assert vd.check_fixture(suppress, leaked, met) == (
        "FAIL",
        "sid 2067457 from 192.168.1.44 present",
    )

    none = vd.check_fixture(suppress, set(), met)
    assert none == ("FAIL", "sid 2067457 from 192.168.1.99 missing")

    unmet = {"threshold": (False, "no file yet")}
    assert vd.check_fixture(suppress, leaked, unmet) == ("SKIPPED", "no file yet")
    assert vd.check_fixture(suppress, leaked, {})[0] == "SKIPPED"


# --- report --------------------------------------------------------------------------------

# Real Suricata 8.0.7 lines from the G11 replay (2026-11-07)
LOG = """\
[8 - Suricata-Main] 2026-11-07 05:11:07 Info: detect: 7 rule files processed. 53492 rules successfully loaded, 0 rules failed, 0 rules skipped
[8 - Suricata-Main] 2026-11-07 05:11:07 Info: threshold-config: Threshold config parsed: 1 rule(s) found
[1 - Suricata-Main] 2026-11-07 05:15:03 Warning: threshold-config: Error opening file: "/etc/nettap/suricata-threshold.config": No such file or directory
"""
CONSOLE = "Info: conf-yaml-loader: Including configuration file /opt/suricata/include-configs/nettap.yaml.\n"


def _alert(
    sid: int, src: str, severity: str = "Informational", msg: str = "ET X"
) -> str:
    metadata = {"signature_severity": [severity]} if severity else {}
    alert = {"signature_id": sid, "signature": msg, "metadata": metadata}
    event = {
        "event_type": "alert",
        "src_ip": src,
        "dest_ip": "192.0.2.53",
        "alert": alert,
    }
    return json.dumps(event) + "\n"


def _out_dir(
    tmp_path,
    eve: str,
    threshold: str = "active (include-configs/nettap.yaml)",
    rc: str = "0",
):
    (tmp_path / "eve-20261107_051052.json").write_text(eve)
    (tmp_path / "suricata.log").write_text(LOG)
    (tmp_path / "runner-console.log").write_text(CONSOLE)
    (tmp_path / "runner-exit").write_text(rc + "\n")
    (tmp_path / "threshold-state").write_text(threshold + "\n")
    (tmp_path / "memory.peak").write_text(str(581 * 2**20) + "\n")
    (tmp_path / "sha256.txt").write_text("# pcap (/x)\nabc  ./a.pcap\n")
    return str(tmp_path)


GOOD_EVE = (
    _alert(2033078, "192.168.1.50")
    + _alert(2067457, vd.OTHER_DEVICE)
    + _alert(2013075, vd.SUPPRESSED_DEVICE, "Major", "ET MALWARE Large DNS Query")
    + _alert(2200000, "10.0.0.1", "", "SURICATA engine event")
    + '{"event_type": "alert", "truncated\n'
)


def test_log_facts_reads_suricata_8_lines():
    facts = vd.log_facts(LOG, CONSOLE)
    assert (facts["loaded"], facts["failed"], facts["rule_files"]) == (53492, 0, 7)
    assert len(facts["threshold"]) == 2
    assert facts["problems"] == [LOG.splitlines()[2]]
    assert facts["includes"] == [CONSOLE.strip()]


def test_report_passes_good_fixtures(tmp_path, capsys):
    assert vd.report("fixtures", _out_dir(tmp_path, GOOD_EVE)) == 0
    out = capsys.readouterr().out
    assert "Rules: 53492 loaded, 0 failed (7 rule files)" in out
    assert "Peak memory (runner cgroup, incl. page cache): 581 MiB" in out
    assert "engine events 1, rule alerts 3: counted 1, activity 2" in out
    assert "Unreadable eve lines: 1" in out
    assert "(none)" in out  # the engine event has no ET severity
    for name in ("activity-stun", "suppress-44", "keep-2013075-44"):
        assert f"PASS     {name}" in out
    assert "abc  ./a.pcap" in out


def test_report_fails_when_44_is_not_suppressed(tmp_path, capsys):
    eve = GOOD_EVE + _alert(2067457, vd.SUPPRESSED_DEVICE)
    assert vd.report("fixtures", _out_dir(tmp_path, eve)) == 1
    assert (
        "FAIL     suppress-44 — sid 2067457 from 192.168.1.44 present"
        in capsys.readouterr().out
    )


def test_report_skips_suppression_until_the_threshold_file_is_loaded(tmp_path, capsys):
    eve = GOOD_EVE + _alert(2067457, vd.SUPPRESSED_DEVICE)
    out_dir = _out_dir(
        tmp_path,
        eve,
        threshold="no /etc/nettap/suricata-threshold.config on the device yet",
    )
    assert vd.report("fixtures", out_dir) == 0
    assert (
        "SKIPPED  suppress-44 — no /etc/nettap/suricata-threshold.config"
        in capsys.readouterr().out
    )


def test_report_flags_a_failed_replay(tmp_path, capsys):
    assert vd.report("own", _out_dir(tmp_path, "", rc="124")) == 2
    out = capsys.readouterr().out
    assert "Runner exit code: 124" in out
    assert "Fixtures:" not in out  # own traffic: report only
