"""
NET-205 accuracy gate: an independent reference for the live bandwidth meter.

Runs inside the daemon container while a known transfer runs from the device being measured:

  sudo docker exec -i nettap-storage-daemon python3 - MAC SECONDS DIRECTION \
      < scripts/remote/live_bandwidth_reference.py > reference.json

It reads every frame to or from MAC on the capture interface with its own AF_PACKET socket,
timestamps each one with the kernel's receive time (SO_TIMESTAMPNS, converted to the meter's
CLOCK_MONOTONIC), sums frame length - 14 (the meter's layer) into 1 ms bins, polls the meter (the
keepalive), and at the end compares each meter tick window with the same window of the reference.

The run is void when the kernel dropped frames on the reference socket or the wall clock stepped.
Gate for DIRECTION ("down" for a download, "up" for an upload), fixed before the run:
  - at least 95 % of the ticks inside the transfer's middle span are valid;
  - at least 15 consecutive eligible windows (both ticks valid, inside the span, >= 1 Mbit/s);
  - every eligible window within 5 % of the reference.
The transfer span is where the reference sees >= 1 Mbit/s in DIRECTION; the middle span drops 3 s
at each end. Progress goes to stderr, the verdict JSON to stdout.
"""

from __future__ import annotations

import ctypes
import json
import math
import socket
import struct
import sys
import threading
import time
import urllib.request

API = "http://localhost:8880"
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
    for prev, cur in zip(timed, timed[1:]):
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
    sock._bpf = buf  # keep the program alive with the socket
    sock.setsockopt(socket.SOL_SOCKET, 33, 256 * 1024 * 1024)  # SO_RCVBUFFORCE
    sock.setsockopt(socket.SOL_SOCKET, SO_TIMESTAMPNS, 1)
    sock.bind((iface, ETH_P_ALL))
    sock.getsockopt(SOL_PACKET, PACKET_STATISTICS, 8)  # clear-on-read: start from zero
    sock.settimeout(0.5)
    return sock


def api(path: str) -> dict:
    with open(TOKEN_PATH) as handle:
        token = handle.read().strip()
    request = urllib.request.Request(
        API + path, headers={"X-NetTap-Daemon-Token": token}
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def run(mac_text: str, seconds: float, direction: str) -> dict:
    mac = bytes.fromhex(mac_text.replace(":", ""))
    first = api(f"/api/live-bandwidth?mac={mac_text}")
    if not first.get("supported"):
        return {"void": f"the meter isn't measuring: {first.get('reason')}"}
    offset = clock_offset()
    bins = Bins(offset)
    sock = open_socket(first["interface"], mac)
    stop, latest = threading.Event(), {"snap": first}

    def poll() -> None:  # the meter's keepalive, and its samples at the end
        while not stop.wait(1.0):
            latest["snap"] = api(f"/api/live-bandwidth?mac={mac_text}")

    poller = threading.Thread(target=poll, daemon=True)
    poller.start()
    buf = bytearray(256)
    end = time.monotonic() + seconds
    frames = 0
    print(
        f"reference running for {seconds:.0f} s on {first['interface']}",
        file=sys.stderr,
    )
    while time.monotonic() < end:
        try:
            length, anc, _, _ = sock.recvmsg_into([buf], 64, socket.MSG_TRUNC)
        except socket.timeout:
            continue
        stamp = next((d for lvl, typ, d in anc if typ == SO_TIMESTAMPNS), None)
        if stamp is None:
            continue
        sec, nsec = struct.unpack("qq", stamp[:16])
        direction_seen = "up" if buf[6:12] == mac else "down"
        bins.add(sec + nsec / 1e9, length - 14, direction_seen)
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
    if drops:
        result["void"] = f"the reference socket dropped {drops} frames"
    elif drift > MAX_CLOCK_DRIFT_S:
        result["void"] = f"the wall clock moved {drift * 1000:.1f} ms during the run"
    result["pass"] = result["void"] is None and result[direction]["pass"]
    return result


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[3] not in ("down", "up"):
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    outcome = run(sys.argv[1].lower(), float(sys.argv[2]), sys.argv[3])
    print(json.dumps(outcome, indent=1))
    sys.exit(0 if outcome.get("pass") else 1)
