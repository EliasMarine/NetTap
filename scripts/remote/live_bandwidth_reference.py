"""
NET-205 accuracy gate: an independent reference for the live bandwidth meter.

Runs inside the daemon container while a known transfer runs from the device being measured:

  sudo docker exec -i nettap-storage-daemon python3 - MAC SECONDS DIRECTION CURL_BYTES \
      < scripts/remote/live_bandwidth_reference.py > reference.json

CURL_BYTES is the body size curl moves, fixed before the run, e.g. from the dev Mac:
  download: curl -o /dev/null -w '%{size_download}\n' 'https://speed.cloudflare.com/__down?bytes=N'
  upload:   head -c N /dev/urandom > /tmp/up.bin
            curl -o /dev/null -w '%{size_upload}\n' --data-binary @/tmp/up.bin \
                https://speed.cloudflare.com/__up
Start curl 10 s after the reference says so and let it finish 10 s before the run ends (the quiet
gaps the meter's counter is read in). curl must print N, or the run doesn't count.

The setting is turned on for the run and put back afterwards. The reference reads every frame to
or from MAC on the capture interface with its own AF_PACKET socket, timestamps each one with the
kernel's receive time (SO_TIMESTAMPNS, converted to the meter's CLOCK_MONOTONIC), sums frame
length - 14 (the meter's layer) into 1 ms bins, polls the meter (the keepalive), and at the end
compares each meter tick window with the same window of the reference.

The run is void when the kernel dropped frames on the reference socket or the wall clock stepped.
Gate for DIRECTION ("down" for a download, "up" for an upload), fixed before the run:
  - window check: at least 95 % of the ticks inside the transfer's middle span are valid; at least
    15 consecutive eligible windows (both ticks valid, inside the span, >= 1 Mbit/s); every
    eligible window within 5 % of the reference;
  - average check (plan section 6): the watch's raw tc byte counter, read in the quiet gaps before
    and after the transfer, within 5 % of curl_bytes x (1 + h) + dup_bytes + unrelated, where h is
    the curl flow's measured header share (see judge_average); void when other traffic or
    retransmissions are too large or a segment partly overlaps data already seen;
  - span check: that raw counter within 1 % of the reference's own bytes over the same span.
The transfer span is where the reference sees >= 1 Mbit/s in DIRECTION; the middle span drops 3 s
at each end. Progress goes to stderr, the verdict JSON to stdout.
"""

from __future__ import annotations

import bisect
import ctypes
import itertools
import json
import math
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.request

from services.live_bandwidth_tc import PREFS, parse_cookie, parse_filter_dump

API = "http://localhost:8880"
SETTING = "/api/settings/live-bandwidth"
TOKEN_PATH = "/run/nettap-auth/daemon-token"
SO_TIMESTAMPNS = 35
PACKET_STATISTICS = 6
SOL_PACKET = 263
ETH_P_ALL = 0x0003
BIN_S = 0.001
ACTIVE_BPS = 1e6
TRIM_S = 3.0
TOLERANCE = 0.05
MIN_RUN = 15
MIN_VALID_SHARE = 0.95
MAX_CLOCK_DRIFT_S = 0.002
SPAN_TOLERANCE = 0.01
MAX_UNRELATED = 0.01  # of the flow's bytes
MAX_DUP = 0.02
QUIET_S = 10.0
HTTPS = 443
SEQ_MOD, SEQ_HALF = 1 << 32, 1 << 31


class Bins:
    """Bytes per direction in 1 ms bins of CLOCK_MONOTONIC, placed by the kernel's timestamp."""

    def __init__(self, offset: float) -> None:
        self.offset = offset  # CLOCK_REALTIME - CLOCK_MONOTONIC
        self.bins: dict[str, dict[int, int]] = {"down": {}, "up": {}}

    def add(self, realtime: float, nbytes: int, direction: str) -> None:
        index = math.floor((realtime - self.offset) / BIN_S)
        bucket = self.bins[direction]
        bucket[index] = bucket.get(index, 0) + nbytes

    def between(self, direction: str, start: float, end: float) -> int:
        """Bytes received in (start, end] of CLOCK_MONOTONIC, to the millisecond."""
        first, last = math.floor(start / BIN_S) + 1, math.floor(end / BIN_S)
        bucket = self.bins[direction]
        return sum(v for k, v in bucket.items() if first <= k <= last)

    def span(self, direction: str) -> tuple[float, float] | None:
        """First and last second where this direction ran at >= ACTIVE_BPS."""
        seconds: dict[int, int] = {}
        for index, nbytes in self.bins[direction].items():
            second = math.floor(index * BIN_S)
            seconds[second] = seconds.get(second, 0) + nbytes
        active = sorted(s for s, n in seconds.items() if n * 8 >= ACTIVE_BPS)
        return (float(active[0]), float(active[-1] + 1)) if active else None


def evaluate(bins: Bins, samples: list[dict], direction: str) -> dict:
    """Compare the meter's tick windows with the reference, and apply the gate."""
    span = bins.span(direction)
    if span is None:
        return {"pass": False, "why": f"no {direction} transfer seen"}
    lo, hi = span[0] + TRIM_S, span[1] - TRIM_S
    field = f"{direction}_bps"
    timed = [s for s in samples if s.get("mono") is not None]
    within = [s["tick"] for s in timed if lo <= s["mono"] <= hi]
    # every tick in the span counts, a missed one (no counter read, so no time) included
    inside = [s for s in samples if within and within[0] <= s["tick"] <= within[-1]]
    valid = [s for s in inside if s.get(field) is not None]
    windows, run, best_run = [], 0, 0
    for prev, cur in itertools.pairwise(timed):
        if not (lo <= prev["mono"] and cur["mono"] <= hi):
            continue
        if cur["tick"] != prev["tick"] + 1:  # a missed tick breaks the run
            run = 0
            continue
        seconds = cur["mono"] - prev["mono"]
        reference = bins.between(direction, prev["mono"], cur["mono"]) * 8 / seconds
        eligible = (
            prev.get(field) is not None
            and cur.get(field) is not None
            and reference >= ACTIVE_BPS
        )
        error = (cur[field] - reference) / reference if eligible else None
        windows.append({"tick": cur["tick"], "meter": cur.get(field), "reference": reference,
                        "error": error, "reason": cur.get("reason")})  # fmt: skip
        run = run + 1 if eligible else 0
        best_run = max(best_run, run)
    errors = [w["error"] for w in windows if w["error"] is not None]
    share = len(valid) / len(inside) if inside else 0.0
    worst = max((abs(e) for e in errors), default=None)
    checks = {
        "valid_share": share >= MIN_VALID_SHARE,
        "longest_run": best_run >= MIN_RUN,
        "every_window": bool(errors) and worst <= TOLERANCE,
    }
    return {
        "pass": all(checks.values()),
        "checks": checks,
        "span": [lo, hi],
        "ticks_inside": len(inside),
        "valid_share": round(share, 4),
        "eligible_windows": len(errors),
        "longest_run": best_run,
        "worst_error": worst,
        "mean_error": sum(errors) / len(errors) if errors else None,
        "reference_bytes_in_span": bins.between(direction, lo, hi),
        "windows": windows,
    }


# ---------------------------------------------------------------------------- flow accounting


def parse_tcp(
    frame: bytes, length: int
) -> tuple[bytes, bytes, int, int, int, int] | None:
    """(src ip, dst ip, src port, dst port, seq, payload bytes) of an IPv4 TCP frame, else None."""
    seen, off = min(length, len(frame)), 14
    if seen < 34:
        return None
    ethertype = struct.unpack_from("!H", frame, 12)[0]
    if ethertype == 0x8100:  # a tag the NIC didn't strip
        ethertype, off = struct.unpack_from("!H", frame, 16)[0], 18
    if ethertype != 0x0800 or seen < off + 20 or frame[off + 9] != 6:
        return None
    ihl = (frame[off] & 0x0F) * 4
    total, frag = struct.unpack_from("!H2xH", frame, off + 2)
    tcp = off + ihl
    if frag & 0x1FFF or ihl < 20 or seen < tcp + 20:
        return None
    sport, dport, seq, _, doff = struct.unpack_from("!HHIIB", frame, tcp)
    src, dst = bytes(frame[off + 12 : off + 16]), bytes(frame[off + 16 : off + 20])
    return src, dst, sport, dport, seq, total - ihl - (doff >> 4) * 4


class Ranges:
    """Disjoint, sorted, merged [start, end) ranges of sequence space."""

    def __init__(self) -> None:
        self.starts: list[int] = []
        self.ends: list[int] = []

    def add(self, start: int, end: int) -> int:
        """Add [start, end) and return how many of its bytes were already covered."""
        # the ranges from lo to hi touch or overlap [start, end)
        lo = bisect.bisect_left(self.ends, start)
        hi = bisect.bisect_right(self.starts, end)
        covered = sum(
            max(0, min(end, self.ends[k]) - max(start, self.starts[k]))
            for k in range(lo, hi)
        )
        if lo < hi:
            start, end = min(start, self.starts[lo]), max(end, self.ends[hi - 1])
        self.starts[lo:hi] = [start]
        self.ends[lo:hi] = [end]
        return covered


class FlowSide:
    """One direction of one TCP flow: frame bytes, unique payload, duplicates, partial overlaps."""

    def __init__(self) -> None:
        self.l3 = self.unique = self.dup_bytes = self.partial = 0
        self.first_data: float | None = None
        self.last_data: float | None = None
        self.last_seq: int | None = None
        self.ranges = Ranges()

    def add(self, l3: int, seq: int, payload: int, mono: float) -> None:
        self.l3 += l3
        if payload <= 0:
            return
        # unwrap: the 64-bit sequence number closest to the last one
        if self.last_seq is not None:
            seq = self.last_seq + (seq - self.last_seq + SEQ_HALF) % SEQ_MOD - SEQ_HALF
        self.last_seq = seq
        covered = self.ranges.add(seq, seq + payload)
        if covered == payload:  # a retransmission: every byte was already seen
            self.dup_bytes += l3
        elif covered:
            self.partial += 1
        self.unique += payload - covered
        self.first_data = mono if self.first_data is None else self.first_data
        self.last_data = mono


class Accounting:
    """Bytes per direction (the meter's layer) and per TCP flow, for frames to or from one MAC."""

    def __init__(self, mac: bytes) -> None:
        self.mac = mac
        self.total = {"down": 0, "up": 0}
        self.flows: dict[tuple, dict[str, FlowSide]] = {}

    def add(self, frame: bytes, length: int, mono: float) -> None:
        direction = "up" if frame[6:12] == self.mac else "down"
        l3 = length - 14
        self.total[direction] += l3
        tcp = parse_tcp(frame, length)
        if tcp is None:
            return
        src, dst, sport, dport, seq, payload = tcp
        key = (
            (src, sport, dst, dport) if direction == "up" else (dst, dport, src, sport)
        )
        sides = self.flows.get(key)
        if sides is None:
            sides = self.flows[key] = {"down": FlowSide(), "up": FlowSide()}
        sides[direction].add(l3, seq, payload, mono)

    def curl_flow(self, direction: str) -> tuple | None:
        """The flow to a remote port 443 with the most bytes in direction: the curl transfer."""
        https = [key for key in self.flows if key[3] == HTTPS]
        return max(https, key=lambda key: self.flows[key][direction].l3, default=None)

    def flow_stats(self, key: tuple) -> dict:
        mac_ip, mac_port, far_ip, far_port = key
        stats: dict = {
            "flow": f"tcp {socket.inet_ntoa(mac_ip)}:{mac_port} <-> "
            f"{socket.inet_ntoa(far_ip)}:{far_port}"
        }
        for direction, side in self.flows[key].items():
            stats[direction] = {
                "flow_l3": side.l3,
                "flow_payload_unique": side.unique,
                "dup_bytes": side.dup_bytes,
                "partial_overlaps": side.partial,
                "unrelated": self.total[direction] - side.l3,
                "first_data": side.first_data,
                "last_data": side.last_data,
            }
        return stats


def judge_average(meter_total: int, curl_bytes: int, stats: dict) -> dict:
    """The average check: the meter's total vs curl's bytes plus the flow's measured header share.

    h = (flow_l3 - dup_bytes) / flow_payload_unique - 1 (TCP/IP headers, TLS and HTTP framing per
    payload byte); expected = curl_bytes x (1 + h) + dup_bytes + unrelated. curl's body bytes leave
    out TLS and HTTP framing, so expect the meter about 0.5 % over: stated, not fitted.
    """
    flow_l3, unique = stats["flow_l3"], stats["flow_payload_unique"]
    dup, unrelated = stats["dup_bytes"], stats["unrelated"]
    if unique <= 0:
        return {"verdict": "VOID", "reasons": ["the flow carried no data"]}
    reasons = []
    if unrelated > MAX_UNRELATED * flow_l3:
        reasons.append(
            f"other traffic was {unrelated / flow_l3:.2%} of the flow (over 1 %)"
        )
    if dup > MAX_DUP * flow_l3:
        reasons.append(
            f"retransmissions were {dup / flow_l3:.2%} of the flow (over 2 %)"
        )
    if stats["partial_overlaps"]:
        reasons.append(
            f"{stats['partial_overlaps']} segments partly overlapped data already seen"
        )
    header_share = (flow_l3 - dup) / unique - 1
    expected = curl_bytes * (1 + header_share) + dup + unrelated
    error = meter_total / expected - 1
    verdict = "VOID" if reasons else "PASS" if abs(error) <= TOLERANCE else "FAIL"
    if verdict == "FAIL":
        reasons.append(f"the meter is {error:+.2%} off the expected bytes (limit 5 %)")
    return {"verdict": verdict, "reasons": reasons, "header_share": header_share,
            "expected": expected, "error": error}  # fmt: skip


def judge_span(meter_total: int, reference_total: int) -> dict:
    """The span check: the meter's raw counter vs the reference's frames over the same span."""
    gap = meter_total - reference_total
    return {
        "pass": abs(gap) <= SPAN_TOLERANCE * reference_total,
        "meter": meter_total,
        "reference": reference_total,
        "error": gap / reference_total if reference_total else None,
    }


def watch_bytes(dump: str, mac: str) -> dict:
    """The raw byte counters of the MAC watch on mac, from ``tc -s -j filter show ... ingress``."""
    keys = {
        (int(item["pref"]), int(item["options"].get("handle", 0))): item["options"].get(
            "keys"
        )
        or {}
        for item in json.loads(dump or "[]")
        if isinstance(item, dict) and isinstance(item.get("options"), dict)
    }
    found: dict = {}
    for direction, field in (("down", "dst_mac"), ("up", "src_mac")):
        pref = PREFS[("mac", direction)][0]
        hits = [
            e
            for e in parse_filter_dump(dump)
            if e.pref == pref
            and parse_cookie(e.cookie)
            and str(keys.get((e.pref, e.handle), {}).get(field, "")).lower() == mac
        ]
        if len(hits) != 1 or hits[0].bytes is None:
            raise ValueError(
                f"no single {direction} counter for {mac} ({len(hits)} found)"
            )
        found[direction], found[f"{direction}_cookie"] = hits[0].bytes, hits[0].cookie
    return found


# ---------------------------------------------------------------------------- live run


def clock_offset() -> float:
    """CLOCK_REALTIME - CLOCK_MONOTONIC, from the tightest of 20 bracketed reads."""
    best = None
    for _ in range(20):
        m0, r, m1 = time.monotonic(), time.time(), time.monotonic()
        if best is None or m1 - m0 < best[0]:
            best = (m1 - m0, r - (m0 + m1) / 2)
    return best[1]


def ether_host_filter(mac: bytes) -> bytes:
    """Classic BPF: accept frames with mac as destination or source (keeps Python's load small)."""
    hi, lo = struct.unpack("!HI", mac)
    code = [
        (0x20, 0, 0, 2), (0x15, 0, 2, lo),  # ld [2]; jeq lo
        (0x28, 0, 0, 0), (0x15, 4, 0, hi),  # ldh [0]; jeq hi -> accept
        (0x20, 0, 0, 8), (0x15, 0, 3, lo),  # ld [8]; jeq lo
        (0x28, 0, 0, 6), (0x15, 0, 1, hi),  # ldh [6]; jeq hi
        (0x06, 0, 0, 0x40000), (0x06, 0, 0, 0),  # ret accept; ret drop
    ]  # fmt: skip
    return b"".join(struct.pack("HBBI", *ins) for ins in code)


def open_socket(iface: str, mac: bytes) -> socket.socket:
    sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_ALL))
    program = ether_host_filter(mac)
    buf = ctypes.create_string_buffer(program)
    fprog = struct.pack("HL", len(program) // 8, ctypes.addressof(buf))
    sock.setsockopt(socket.SOL_SOCKET, 26, fprog)  # SO_ATTACH_FILTER
    # OLD CODE START: socket objects take no new attributes (AttributeError on the G11), and the
    # kernel has its own copy once setsockopt returns, so nothing needs to keep buf alive
    # sock._bpf = buf  # keep the program alive with the socket
    # OLD CODE END
    sock.setsockopt(socket.SOL_SOCKET, 33, 256 * 1024 * 1024)  # SO_RCVBUFFORCE
    sock.setsockopt(socket.SOL_SOCKET, SO_TIMESTAMPNS, 1)
    sock.bind((iface, ETH_P_ALL))
    sock.getsockopt(SOL_PACKET, PACKET_STATISTICS, 8)  # clear-on-read: start from zero
    sock.settimeout(0.5)
    return sock


def api(path: str, body: dict | None = None) -> dict:
    """GET path, or PUT body to it, with the daemon token (never printed)."""
    with open(TOKEN_PATH) as handle:
        token = handle.read().strip()
    request = urllib.request.Request(
        API + path,
        data=None if body is None else json.dumps(body).encode(),
        method="GET" if body is None else "PUT",
        headers={"X-NetTap-Daemon-Token": token, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def read_counter(iface: str, mac: str) -> tuple[float, dict]:
    """The watch's raw tc counters, and the CLOCK_MONOTONIC time of the read."""
    start = time.monotonic()
    done = subprocess.run(
        ["tc", "-s", "-j", "filter", "show", "dev", iface, "ingress"],
        capture_output=True, text=True, timeout=10, check=True,
    )  # fmt: skip
    return (start + time.monotonic()) / 2, watch_bytes(done.stdout, mac)


def receive(sock: socket.socket, buf: bytearray) -> tuple[int, float] | None:
    """(frame length, kernel receive time on CLOCK_REALTIME), or None after the socket's timeout."""
    try:
        length, anc, _, _ = sock.recvmsg_into([buf], 64, socket.MSG_TRUNC)
    except TimeoutError:
        return None
    stamp = next((d for _, typ, d in anc if typ == SO_TIMESTAMPNS), None)
    if stamp is None:
        return None
    sec, nsec = struct.unpack("qq", stamp[:16])
    return length, sec + nsec / 1e9


def run(mac_text: str, seconds: float, direction: str, curl_bytes: int) -> dict:
    """Turn the setting on for the run and put the owner's value back afterwards."""
    original = api(SETTING)["enabled"]
    api(SETTING, {"enabled": True})
    try:
        return measure(mac_text, seconds, direction, curl_bytes)
    finally:
        api(SETTING, {"enabled": original})
        print(f"live bandwidth is back {'on' if original else 'off'}", file=sys.stderr)


def measure(mac_text: str, seconds: float, direction: str, curl_bytes: int) -> dict:
    mac = bytes.fromhex(mac_text.replace(":", ""))
    first = api(f"/api/live-bandwidth?mac={mac_text}")
    if not first.get("supported"):
        return {"void": f"the meter isn't measuring: {first.get('reason')}"}
    iface = first["interface"]
    offset = clock_offset()
    bins, acc = Bins(offset), Accounting(mac)
    sock = open_socket(iface, mac)
    stop, latest = threading.Event(), {"snap": first}

    def poll() -> None:  # the meter's keepalive, and its samples at the end
        while not stop.wait(1.0):
            latest["snap"] = api(f"/api/live-bandwidth?mac={mac_text}")

    poller = threading.Thread(target=poll, daemon=True)
    poller.start()
    buf = bytearray(256)
    t_a, read_a = read_counter(iface, mac_text)

    def record(length: int, realtime: float) -> None:
        bins.add(realtime, length - 14, "up" if buf[6:12] == mac else "down")
        # the average checks cover exactly the counter's span
        if realtime - offset > t_a:
            acc.add(buf, length, realtime - offset)

    end = time.monotonic() + seconds
    print(f"reference running for {seconds:.0f} s on {iface}: start the transfer in "
          f"{QUIET_S:.0f} s and let it finish {QUIET_S:.0f} s before the end", file=sys.stderr)  # fmt: skip
    frames = 0
    while time.monotonic() < end:
        got = receive(sock, buf)
        if got:
            record(*got)
            frames += 1
    t_b, read_b = read_counter(iface, mac_text)
    while (got := receive(sock, buf)) and got[1] - offset <= t_b:  # frames still queued
        record(*got)
        frames += 1
    packets, drops = struct.unpack(
        "II", sock.getsockopt(SOL_PACKET, PACKET_STATISTICS, 8)
    )
    drift = abs(clock_offset() - offset)
    stop.set()
    poller.join()
    snap = api(f"/api/live-bandwidth?mac={mac_text}")
    result = {
        "void": None,
        "frames": frames,
        "kernel_packets": packets,
        "kernel_drops": drops,
        "clock_drift_ms": round(drift * 1000, 3),
        "offloads": snap.get("offloads"),
        "layer": snap.get("layer"),
        "direction": direction,
        "down": evaluate(bins, snap["samples"], "down"),
        "up": evaluate(bins, snap["samples"], "up"),
    }
    checks, void = averages(acc, read_a, read_b, (t_a, t_b), direction, curl_bytes)
    result.update(checks)
    if drops:
        result["void"] = f"the reference socket dropped {drops} frames"
    elif drift > MAX_CLOCK_DRIFT_S:
        result["void"] = f"the wall clock moved {drift * 1000:.1f} ms during the run"
    else:
        result["void"] = void
    result["pass"] = (
        result["void"] is None
        and result[direction]["pass"]
        and result["average"]["verdict"] == "PASS"
        and all(check["pass"] for check in result["span_check"].values())
    )
    return result


def averages(acc: Accounting, read_a: dict, read_b: dict, span: tuple[float, float],
             direction: str, curl_bytes: int) -> tuple[dict, str | None]:  # fmt: skip
    """The average and span checks between the two counter reads, and why they're void (if so)."""
    meter = {d: read_b[d] - read_a[d] for d in ("down", "up")}
    out: dict = {
        "meter_total": meter,
        "reference_total": dict(acc.total),
        "span_check": {d: judge_span(meter[d], acc.total[d]) for d in meter},
    }
    key = acc.curl_flow(direction)
    if key is None:
        out["average"] = {
            "verdict": "VOID",
            "reasons": ["no TCP flow to port 443 seen"],
        }
        return out, "no curl flow seen"
    out["flow"] = acc.flow_stats(key)
    print(f"curl flow: {out['flow']['flow']}", file=sys.stderr)
    side = out["flow"][direction]
    out["average"] = judge_average(meter[direction], curl_bytes, side)
    if any(read_a[f"{d}_cookie"] != read_b[f"{d}_cookie"] for d in meter):
        return out, "the watch was replaced during the run (its counters restarted)"
    if out["average"]["verdict"] == "VOID":
        return out, "; ".join(out["average"]["reasons"])
    if side["first_data"] - span[0] < QUIET_S or span[1] - side["last_data"] < QUIET_S:
        return out, f"the transfer didn't leave {QUIET_S:.0f} s of quiet on both sides"
    return out, None


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) != 4 or args[2] not in ("down", "up") or not args[3].isdigit():
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    outcome = run(args[0].lower(), float(args[1]), args[2], int(args[3]))
    print(json.dumps(outcome, indent=1))
    sys.exit(0 if outcome.get("pass") else 1)
