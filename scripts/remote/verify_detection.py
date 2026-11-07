#!/usr/bin/env python3
"""Fixture PCAPs and the replay report behind scripts/remote/verify-detection.sh (NET-191).

Standard library only. On the device it runs inside a throwaway container of the live
Suricata image (no network), never on the host:
  python3 verify_detection.py write-fixtures <pcap-dir>
  python3 verify_detection.py report <fixtures|own> <out-dir>

The report reads what the runner left in <out-dir>/engine (eve*.json, suricata.log, memory.peak)
and what the shell script wrote in <out-dir> (runner-console.log, runner-exit, threshold-state,
sha256.txt), and prints it; the shell script saves the output as report.txt. The runner can write
only engine/, so nothing it plants can redirect a file the host writes.
Exit codes: 0 ok, 1 a fixture failed, 2 the replay itself failed.
"""

import glob
import ipaddress
import json
import os
import re
import struct
import sys
from collections import Counter

# 2026-01-01T00:00:00Z, fixed so every run writes identical PCAPs
PCAP_FIRST_TS = 1767225600
# Runs Mysterium/Traffmonetizer on purpose (owner, 2026-11-06)
SUPPRESSED_DEVICE = "192.168.1.44"
OTHER_DEVICE = "192.168.1.99"
RESOLVER = "192.0.2.53"  # TEST-NET-1; the replay container has no network anyway
ACTIVITY_SEVERITIES = ("Informational", "Unknown")  # slice 1: stored, not counted


# --- packets -------------------------------------------------------------------------------


def ipv4_checksum(header: bytes) -> int:
    total = sum(struct.unpack(f"!{len(header) // 2}H", header))
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return ~total & 0xFFFF


def udp_frame(src: str, sport: int, dst: str, dport: int, payload: bytes) -> bytes:
    """Ethernet II / IPv4 / UDP frame. UDP checksum 0 means "none" in IPv4."""
    udp = struct.pack("!HHHH", sport, dport, 8 + len(payload), 0) + payload
    ip = struct.pack(
        "!BBHHHBBH4s4s",
        0x45, 0, 20 + len(udp), 0, 0, 64, 17, 0,
        ipaddress.IPv4Address(src).packed, ipaddress.IPv4Address(dst).packed,
    )  # fmt: skip
    ip = ip[:10] + struct.pack("!H", ipv4_checksum(ip)) + ip[12:]
    ethernet = bytes.fromhex("0200000000020200000000010800")  # dst, src, IPv4
    return ethernet + ip + udp


def dns_query(name: str, txid: int) -> bytes:
    """Standard query (RD set), one question, type A, class IN."""
    labels = name.split(".")
    assert all(0 < len(label) <= 63 for label in labels), name
    qname = b"".join(bytes([len(label)]) + label.encode() for label in labels) + b"\x00"
    return (
        struct.pack("!HHHHHH", txid, 0x0100, 1, 0, 0, 0)
        + qname
        + struct.pack("!HH", 1, 1)
    )


def stun_binding_request(txid: bytes = b"NetTapFixtur") -> bytes:
    """RFC 5389 Binding Request: type 0x0001, length 0, magic cookie, 12-byte transaction id."""
    assert len(txid) == 12
    return struct.pack("!HHI", 0x0001, 0, 0x2112A442) + txid


def write_pcap(path: str, frames: list, first_ts: int) -> None:
    """Classic libpcap file (microsecond, Ethernet), one packet per second from first_ts."""
    with open(path, "wb") as f:
        f.write(struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1))
        for i, frame in enumerate(frames):
            f.write(struct.pack("<IIII", first_ts + i, 0, len(frame), len(frame)))
            f.write(frame)


# --- fixtures ------------------------------------------------------------------------------

# 5 x 63-byte labels: the DNS payload is 345 bytes, over 2013075's dsize:>300.
LONG_NAME = ".".join(["c" * 63] * 5) + ".example"

# One PCAP per fixture. packets: (src, sport, dst, dport, UDP payload). expect: an alert with
# this SID from this source must be present (True) or absent (False). needs: a precondition;
# when the run doesn't meet it the fixture is SKIPPED with the reason. Slices 2-3 append here.
FIXTURES = [
    {
        "name": "activity-stun",
        # 2033078 ET INFO STUN Binding Request On Non-Standard High Port (Informational):
        # udp $HOME_NET -> $EXTERNAL_NET [!3478,1023:], |00 01| at 0, |21 12 a4 42| at 4
        "packets": [
            ("192.168.1.50", 50000, "203.0.113.10", 19302, stun_binding_request())
        ],
        "expect": [{"sid": 2033078, "src": "192.168.1.50", "present": True}],
    },
    {
        "name": "suppress-44",
        # 2067457 ET ADWARE_PUP DNS Query to Bandwidth Sharing Tool Domain (mysterium .network):
        # dns $HOME_NET -> any, dns.query; dotprefix; content:".mysterium.network"; endswith
        "needs": "threshold",
        "packets": [
            (
                SUPPRESSED_DEVICE,
                50001,
                RESOLVER,
                53,
                dns_query("node1.mysterium.network", 0x4401),
            ),
            (
                OTHER_DEVICE,
                50001,
                RESOLVER,
                53,
                dns_query("node1.mysterium.network", 0x9901),
            ),
        ],
        "expect": [
            {"sid": 2067457, "src": SUPPRESSED_DEVICE, "present": False},
            {"sid": 2067457, "src": OTHER_DEVICE, "present": True},
        ],
    },
    {
        "name": "keep-2013075-44",
        # 2013075 ET MALWARE Large DNS Query possible covert channel (Major): udp $HOME_NET -> any 53,
        # |01 00 00 01 00 00 00 00 00 00| at offset 2, dsize:>300, none of youtube/sophosxl/...
        "packets": [
            (SUPPRESSED_DEVICE, 50002, RESOLVER, 53, dns_query(LONG_NAME, 0x4402))
        ],
        "expect": [{"sid": 2013075, "src": SUPPRESSED_DEVICE, "present": True}],
    },
]


def write_fixtures(pcap_dir: str) -> None:
    for i, fixture in enumerate(FIXTURES):
        frames = [udp_frame(*packet) for packet in fixture["packets"]]
        write_pcap(
            os.path.join(pcap_dir, f"{fixture['name']}.pcap"),
            frames,
            PCAP_FIRST_TS + 60 * i,
        )
        print(f"   wrote {fixture['name']}.pcap ({len(frames)} packets)")


def check_fixture(fixture: dict, seen: set, met: dict) -> tuple:
    """(PASS|FAIL|SKIPPED, reason). seen holds (sid, src_ip) of every alert in the run."""
    need = fixture.get("needs")
    if need and not met.get(need, (False, ""))[0]:
        return "SKIPPED", met.get(need, (False, f"unknown precondition {need!r}"))[1]
    wrong = [
        f"sid {e['sid']} from {e['src']} {'missing' if e['present'] else 'present'}"
        for e in fixture["expect"]
        if ((e["sid"], e["src"]) in seen) != e["present"]
    ]
    return ("FAIL", "; ".join(wrong)) if wrong else ("PASS", "")


# --- report --------------------------------------------------------------------------------


def read_alerts(out_dir: str) -> tuple:
    """(alerts, unreadable line count) from every eve*.json in out_dir."""
    alerts, bad = [], 0
    for path in sorted(glob.glob(os.path.join(out_dir, "eve*.json"))):
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    event = json.loads(line)
                except ValueError:
                    bad += 1
                    continue
                if event.get("event_type") == "alert":
                    alerts.append(slim_alert(event))
    return alerts, bad


def slim_alert(event: dict) -> dict:
    alert = event.get("alert") or {}
    severity = (alert.get("metadata") or {}).get("signature_severity") or ["(none)"]
    return {
        "sid": alert.get("signature_id"),
        "msg": alert.get("signature", ""),
        "severity": severity[0],
        "src": event.get("src_ip"),
        "dst": event.get("dest_ip"),
    }


LOADED_RE = re.compile(r"(\d+) rules successfully loaded, (\d+) rules failed")
FILES_RE = re.compile(r"(\d+) rule files? processed")


def log_facts(log_text: str, console_text: str) -> dict:
    """Rule counts, problems, threshold and include lines from suricata.log; includes come from
    the console, as Suricata reads them before its log file is open.
    Suricata 8 log lines look like "[tid - thread] date Level: module: message"."""
    loaded = LOADED_RE.findall(log_text)
    files = FILES_RE.findall(log_text)
    lines = log_text.splitlines()
    return {
        "loaded": int(loaded[-1][0]) if loaded else None,
        "failed": int(loaded[-1][1]) if loaded else None,
        "rule_files": int(files[-1]) if files else None,
        "problems": [ln for ln in lines if " Error: " in ln or " Warning: " in ln],
        "threshold": [ln for ln in lines if "threshold-config:" in ln],
        "includes": [
            ln
            for ln in console_text.splitlines()
            if "Including configuration file" in ln
        ],
    }


def threshold_met(out_dir: str) -> tuple:
    """(met, reason): the shell's verdict on whether this run loads the device threshold file."""
    state = read_text(os.path.join(out_dir, "threshold-state"), "unknown").strip()
    return (True, "") if state.startswith("active") else (False, state)


def read_text(path: str, default: str = "") -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return default


def is_engine_event(alert: dict) -> bool:
    return alert["msg"].startswith("SURICATA ")


def summary_lines(alerts: list, bad: int) -> list:
    rule_alerts = [a for a in alerts if not is_engine_event(a)]
    activity = sum(a["severity"] in ACTIVITY_SEVERITIES for a in rule_alerts)
    engine, counted = len(alerts) - len(rule_alerts), len(rule_alerts) - activity
    lines = [
        (
            f"Alerts: {len(alerts)} (engine events {engine}, rule alerts {len(rule_alerts)}: "
            f"counted {counted}, activity {activity})"
        )
    ]
    if bad:
        lines.append(f"Unreadable eve lines: {bad}")
    lines.append("By ET severity (signature_severity):")
    for severity, n in Counter(a["severity"] for a in alerts).most_common():
        lines.append(f"   {severity:<14} {n}")
    by_sid = Counter(a["sid"] for a in alerts)
    lines.append(f"Distinct SIDs: {len(by_sid)}")
    lines.append("Top 10 SIDs:")
    first = {}
    for a in alerts:
        first.setdefault(a["sid"], a)
    for sid, n in by_sid.most_common(10):
        lines.append(
            f"   {n:>8}  {sid}  [{first[sid]['severity']}]  {first[sid]['msg']}"
        )
    for side, label in (("src", "source"), ("dst", "destination")):
        ips = Counter(a[side] for a in alerts)
        lines.append(f"Devices alerted as {label}: {len(ips)} distinct; top 10:")
        lines += [f"   {n:>8}  {ip}" for ip, n in ips.most_common(10)]
    return lines


def report(mode: str, out_dir: str) -> int:
    engine = os.path.join(out_dir, "engine")
    alerts, bad = read_alerts(engine)
    facts = log_facts(
        read_text(os.path.join(engine, "suricata.log")),
        read_text(os.path.join(out_dir, "runner-console.log")),
    )
    runner_exit = read_text(os.path.join(out_dir, "runner-exit"), "?").strip()
    peak = read_text(os.path.join(engine, "memory.peak")).strip()
    threshold = read_text(os.path.join(out_dir, "threshold-state"), "unknown").strip()
    print(f"=== Replay report ({mode}) ===")
    print(f"Runner exit code: {runner_exit}")
    rules = f"{facts['loaded']} loaded, {facts['failed']} failed"
    print(f"Rules: {rules} ({facts['rule_files']} rule files)")
    print(
        "Peak memory (runner cgroup, incl. page cache): "
        + (f"{int(peak) / 2**20:.0f} MiB" if peak.isdigit() else "n/a")
    )
    print(f"Device threshold file: {threshold}")
    for line in facts["includes"] + facts["threshold"]:
        print(f"   {line.strip()}")
    for line in facts["problems"][:20]:
        print(f"Suricata: {line.strip()}")
    print()
    for line in summary_lines(alerts, bad):
        print(line)
    status = 0 if runner_exit == "0" and facts["loaded"] else 2
    if mode == "fixtures":
        status = max(status, print_fixtures(alerts, out_dir))
    print()
    print("SHA-256 of every input:")
    print(read_text(os.path.join(out_dir, "sha256.txt"), "   (missing)\n").rstrip())
    return status


def print_fixtures(alerts: list, out_dir: str) -> int:
    seen = {(a["sid"], a["src"]) for a in alerts}
    met = {"threshold": threshold_met(out_dir)}
    print()
    print("Fixtures:")
    failed = 0
    for fixture in FIXTURES:
        result, reason = check_fixture(fixture, seen, met)
        failed += result == "FAIL"
        print(f"   {result:<8} {fixture['name']}" + (f" — {reason}" if reason else ""))
    print("Not fixturable here: abuse.ch SSLBL (needs a real blacklisted certificate),")
    print("   ET Pro (no code)")
    return 1 if failed else 0


def main(argv: list) -> int:
    if len(argv) == 3 and argv[1] == "write-fixtures":
        write_fixtures(argv[2])
        return 0
    if len(argv) == 4 and argv[1] == "report" and argv[2] in ("fixtures", "own"):
        return report(argv[2], argv[3])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
