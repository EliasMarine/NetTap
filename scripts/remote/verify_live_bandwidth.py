"""
NET-205 release gate for the live bandwidth meter. Runs inside the daemon container (root,
NET_ADMIN, NET_RAW, host network), where the meter's own code is importable:

  sudo docker exec -i nettap-storage-daemon python3 - kernel < scripts/remote/verify_live_bandwidth.py
  sudo docker exec -i nettap-storage-daemon python3 - bench < scripts/remote/verify_live_bandwidth.py
  sudo docker exec -i nettap-storage-daemon python3 - lifecycle [MAC] < scripts/remote/verify_live_bandwidth.py

kernel     the meter's own filter lines, on a throwaway veth pair, count known frames exactly
bench      the filters' per-packet CPU cost on the veth pair (IMIX share of one core must be <= 5 %)
lifecycle  the API on the capture interface: start, idle stop, the cap, nothing foreign touched

One PASS/FAIL line per check; exit 0 only when every check passed. The daemon token is read from
its volume and never printed.
"""

import contextlib
import json
import os
import socket
import statistics
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

from services.dhcp_gateway_net import validate_interface_name
from services.live_bandwidth_tc import (
    PREFS,
    Key,
    build_filter_lines,
    delete_args,
    parse_cookie,
    parse_filter_dump,
)

A, B = "nlbv0", "nlbv1"  # frames sent on A arrive on B's ingress, where the filters sit
TEST_MAC, PEER_MAC, OTHER_MAC = (
    "02:4e:54:00:00:01",
    "02:4e:54:00:00:02",
    "02:4e:54:00:00:99",
)
TEST_IP, PEER_IP, OTHER_IP = "192.0.2.10", "192.0.2.20", "192.0.2.99"  # TEST-NET-1
MCAST_MAC, MCAST_IP = "01:00:5e:00:00:fb", "224.0.0.251"
MAC_DOWN, MAC_UP = PREFS[("mac", "down")][0], PREFS[("mac", "up")][0]
IP_DOWN, IP_UP = PREFS[("ip", "down")][0], PREFS[("ip", "up")][0]
VLAN_DOWN, VLAN_UP = PREFS[("vlan", "down")][0], PREFS[("vlan", "up")][0]
K = 1000
BENCH_FRAMES = 1_000_000
MIXES = {"min": [60], "imix": [60] * 7 + [590] * 4 + [1514], "full": [1514]}
API = "http://localhost:8880"
TOKEN_PATH = "/run/nettap-auth/daemon-token"
SYS_NET = os.environ.get("HOST_SYS_NET", "/host/sys/class/net")
DEV_MAC = "bc:89:c1:e1:8a:d6"  # the dev Mac on the G11's mirrored link
IDLE_WAIT_S = 20

RESULTS: list[bool] = []


def check(ok: bool, what: str) -> None:
    RESULTS.append(bool(ok))
    print(("PASS  " if ok else "FAIL  ") + what, flush=True)


def sh(*argv: str, stdin: str | None = None) -> str:
    done = subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=30)
    if done.returncode:
        raise RuntimeError(f"{' '.join(argv)}: {done.stderr.strip()}")
    return done.stdout


def line_rate_pps(sizes: list[int]) -> float:
    """Frames per second at 1 Gbit/s (each frame also has FCS 4 + preamble 8 + gap 12 bytes)."""
    return 1e9 / (8 * statistics.mean(s + 24 for s in sizes))


# ---------------------------------------------------------------------------- veth helpers


def frame(dst, src, ip_src, ip_dst, size, ip_len=None, vlan=None) -> bytes:
    """A size-byte Ethernet frame with an IPv4 header (ip_len: the IP length; padding after)."""
    head = bytes.fromhex(dst.replace(":", "")) + bytes.fromhex(src.replace(":", ""))
    head += (
        struct.pack("!HH", 0x8100, vlan) if vlan is not None else b""
    ) + b"\x08\x00"
    ip = struct.pack(
        "!BBHHHBBH4s4s", 0x45, 0, ip_len or size - len(head), 0, 0, 64, 17, 0,
        socket.inet_aton(ip_src), socket.inet_aton(ip_dst),
    )  # fmt: skip
    return (head + ip).ljust(size, b"\0")


@contextlib.contextmanager
def veth():
    with contextlib.suppress(RuntimeError):
        sh("ip", "link", "del", A)  # left over from an aborted run
    sh("ip", "link", "add", A, "type", "veth", "peer", "name", B)
    sock = None
    try:
        for dev in (A, B):
            with contextlib.suppress(
                RuntimeError
            ):  # no IPv6 link-local: the pair stays silent
                sh("ip", "link", "set", "dev", dev, "addrgenmode", "none")
            sh("ip", "link", "set", "dev", dev, "up")
        sh("tc", "qdisc", "add", "dev", B, "clsact")
        sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW)
        sock.bind((A, 0))
        yield sock
    finally:
        if sock is not None:
            sock.close()
        sh("ip", "link", "del", A)


def rx_packets() -> int:
    with open(os.path.join(SYS_NET, B, "statistics", "rx_packets")) as handle:
        return int(handle.read())


def send(sock, data: bytes, count: int) -> None:
    for _ in range(count):
        sock.send(data)


def add(lines: list[str]) -> None:
    sh("tc", "-batch", "-", stdin="\n".join(lines) + "\n")


def counters() -> dict:
    time.sleep(0.1)  # let a deferred softirq finish counting
    dump = sh("tc", "-s", "-j", "filter", "show", "dev", B, "ingress")
    return {(e.pref, e.handle): e for e in parse_filter_dump(dump)}


def fresh_clsact() -> None:
    sh("tc", "qdisc", "del", "dev", B, "clsact")
    sh("tc", "qdisc", "add", "dev", B, "clsact")


# ---------------------------------------------------------------------------- kernel


def kernel() -> None:
    with veth() as sock:
        add(
            build_filter_lines(B, Key("mac", TEST_MAC), 0, 1)
            + build_filter_lines(B, Key("ip", TEST_IP), 1, 1)
        )
        frames = [
            frame(TEST_MAC, PEER_MAC, PEER_IP, TEST_IP, 1514),  # download
            frame(
                TEST_MAC, PEER_MAC, PEER_IP, TEST_IP, 1518, vlan=10
            ),  # download, 802.1Q
            frame(PEER_MAC, TEST_MAC, TEST_IP, PEER_IP, 60, ip_len=38),  # tiny upload
            frame(MCAST_MAC, TEST_MAC, TEST_IP, MCAST_IP, 1514),  # multicast upload
            frame(PEER_MAC, OTHER_MAC, OTHER_IP, PEER_IP, 1514),  # someone else
        ]
        before = rx_packets()
        for data in frames:
            send(sock, data, K)
        got_frames = rx_packets() - before
        check(
            got_frames == K * len(frames),
            f"the veth pair delivered every frame ({got_frames})",
        )
        got = counters()
        expect = {
            (MAC_DOWN, 1): (
                3000,
                2,
                "MAC download: plain + 802.1Q, the tag not counted",
            ),
            (MAC_UP, 1): (
                1546,
                2,
                "MAC upload: a 38-byte packet counts 46, multicast counts",
            ),
            (IP_DOWN, 2): (1500, 1, "IP download, plain frames only"),
            (VLAN_DOWN, 2): (1500, 1, "IP download over 802.1Q, the tag not counted"),
            (IP_UP, 2): (
                1546,
                2,
                "IP upload: 46 for the tiny packet, multicast counts",
            ),
            (VLAN_UP, 2): (0, 0, "IP upload over 802.1Q: none sent, none counted"),
        }
        for ident, (per_k, packets, what) in expect.items():
            entry = got.get(ident)
            seen = (entry.bytes, entry.packets) if entry else None
            check(seen == (per_k * K, packets * K), f"{what}: {seen}")
        check(
            all(
                parse_cookie(got[i].cookie) == (i[1] - 1, 1) for i in expect if i in got
            ),
            "every counter carries its own watch's cookie",
        )
        shared_stages(sock)


def shared_stages(sock) -> None:
    fresh_clsact()
    keys = [Key("mac", f"02:4e:54:00:01:{n:02x}") for n in range(3)]
    keys += [
        Key("ip", f"192.0.2.{100 + n}") for n in range(3)
    ]  # slots 0-5, handles 1-6
    add(
        [
            line
            for slot, key in enumerate(keys)
            for line in build_filter_lines(B, key, slot, 1)
        ]
    )

    def to(
        key: Key,
    ) -> bytes:  # a download frame for this key alone, counted as 1,000 bytes
        if key.kind == "mac":
            return frame(key.value, PEER_MAC, PEER_IP, OTHER_IP, 1014)
        return frame(PEER_MAC, OTHER_MAC, PEER_IP, key.value, 1014)

    def down(got: dict, slot: int):
        return got.get((MAC_DOWN if slot < 3 else IP_DOWN, slot + 1))

    sent = {slot: 100 * (slot + 1) for slot in range(6)}
    for slot, key in enumerate(keys):
        send(sock, to(key), sent[slot])
    got = counters()
    check(
        all(down(got, s) and down(got, s).bytes == sent[s] * 1000 for s in range(6)),
        "six watches sharing the stages each count only their own traffic",
    )
    check(
        not [
            e
            for (pref, _), e in got.items()
            if pref not in (MAC_DOWN, IP_DOWN) and e.bytes
        ],
        "no upload or 802.1Q counter moved",
    )

    flowing = {0: 0, 2: 0, 3: 0}
    stop = threading.Event()

    def flow() -> None:
        with socket.socket(socket.AF_PACKET, socket.SOCK_RAW) as tx:
            tx.bind((A, 0))
            data = {s: to(keys[s]) for s in flowing}
            while not stop.is_set():
                for s in flowing:
                    tx.send(data[s])
                    flowing[s] += 1

    worker = threading.Thread(target=flow)
    worker.start()
    time.sleep(0.2)
    lines = [" ".join(delete_args(B, pref, 2)) for pref in (MAC_DOWN, MAC_UP)]
    sh("tc", "-batch", "-", stdin="\n".join(lines) + "\n")
    time.sleep(0.2)
    stop.set()
    worker.join()
    got = counters()
    check(
        (MAC_DOWN, 2) not in got and (MAC_UP, 2) not in got,
        "the deleted watch's filters are gone",
    )
    check(
        all(down(got, s).bytes == (sent[s] + flowing[s]) * 1000 for s in flowing),
        f"its neighbours kept counting through the delete ({sum(flowing.values())} frames)",
    )
    check(
        all(parse_cookie(down(got, s).cookie) == (s, 1) for s in (0, 2, 3, 4, 5)),
        "the neighbours' handles and cookies are intact",
    )

    reused = Key("mac", "02:4e:54:00:01:09")
    add(build_filter_lines(B, reused, 1, 2))
    send(
        sock, to(keys[1]), 50
    )  # the old key's traffic must not land on the reused handle
    send(sock, to(reused), 70)
    entry = counters().get((MAC_DOWN, 2))
    check(
        entry is not None
        and entry.bytes == 70_000
        and parse_cookie(entry.cookie) == (1, 2),
        "a reused slot counts only its new key, under the new generation",
    )


# ---------------------------------------------------------------------------- bench


def cpu_ticks(cpu: int) -> int:
    """system + irq + softirq clock ticks on one CPU."""
    with open("/proc/stat") as handle:
        for line in handle:
            if line.startswith(f"cpu{cpu} "):
                fields = [int(v) for v in line.split()[1:]]
                return fields[2] + fields[5] + fields[6]
    raise RuntimeError(f"cpu{cpu} is not in /proc/stat")


def configure(setup: str) -> None:
    with contextlib.suppress(RuntimeError):
        sh("tc", "qdisc", "del", "dev", B, "clsact")
    if setup == "none":
        return
    sh("tc", "qdisc", "add", "dev", B, "clsact")
    if (
        setup == "eight"
    ):  # traffic hits a watched MAC and a watched IP, like a real device
        keys = [Key("mac", TEST_MAC)] + [
            Key("mac", f"02:4e:54:00:01:{n:02x}") for n in range(3)
        ]
        keys += [Key("ip", TEST_IP)] + [
            Key("ip", f"192.0.2.{100 + n}") for n in range(3)
        ]
        add(
            [
                line
                for slot, key in enumerate(keys)
                for line in build_filter_lines(B, key, slot, 1)
            ]
        )


def measure(sock, frames: list[bytes], cpu: int) -> float:
    """CPU nanoseconds per frame the peer received (system + irq + softirq on the pinned CPU)."""
    rounds = BENCH_FRAMES // len(frames)
    rx0, c0 = rx_packets(), cpu_ticks(cpu)
    for _ in range(rounds):
        for data in frames:
            sock.send(data)
    c1, received = cpu_ticks(cpu), rx_packets() - rx0
    return (c1 - c0) * 1e9 / os.sysconf("SC_CLK_TCK") / max(received, 1)


def bench() -> None:
    # The sender is pinned, and veth delivers in its softirq on the same CPU, so the filters' cost
    # lands on that CPU's counters. All-CPU accounting is swamped by the capture stack's own load.
    cpu = max(os.sched_getaffinity(0))
    os.sched_setaffinity(0, {cpu})
    health = HealthWatch()
    health.start()
    try:
        with veth() as sock:
            for name, sizes in MIXES.items():
                frames = [frame(TEST_MAC, PEER_MAC, PEER_IP, TEST_IP, s) for s in sizes]
                cost = {}
                for setup in ("none", "empty", "eight"):
                    configure(setup)
                    cost[setup] = statistics.median(
                        measure(sock, frames, cpu) for _ in range(3)
                    )
                empty, eight = (
                    cost["empty"] - cost["none"],
                    cost["eight"] - cost["none"],
                )
                share = eight * line_rate_pps(sizes) / 1e9
                print(
                    f"INFO  {name}: empty clsact +{empty:.0f} ns/frame, 8 watches "
                    f"+{eight:.0f} ns/frame = {share:.1%} of one core at 1 Gbit/s "
                    f"({line_rate_pps(sizes):,.0f} frames/s)",
                    flush=True,
                )
                if name == "imix":
                    check(
                        share <= 0.05,
                        f"IMIX at 1 Gbit/s costs {share:.1%} of one core (<= 5 %)",
                    )
    finally:
        health.stop()
    check(
        health.worst < 1.0, f"/api/health stayed under 1 s ({health.worst:.2f} s worst)"
    )


# ---------------------------------------------------------------------------- lifecycle


class HealthWatch(threading.Thread):
    """Times /api/health twice a second while a check runs."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.worst = 0.0
        self._stop = threading.Event()

    def run(self) -> None:
        while not self._stop.wait(0.5):
            start = time.monotonic()
            try:
                urllib.request.urlopen(API + "/api/health", timeout=5).read()
                self.worst = max(self.worst, time.monotonic() - start)
            except OSError:
                self.worst = max(self.worst, 99.0)

    def stop(self) -> None:
        self._stop.set()
        self.join()


def api(path: str) -> tuple[int, dict]:
    with open(TOKEN_PATH) as handle:
        token = handle.read().strip()
    request = urllib.request.Request(
        API + path, headers={"X-NetTap-Daemon-Token": token}
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)


def interfaces() -> list[str]:
    names = []
    for name in sorted(os.listdir(SYS_NET)):
        with contextlib.suppress(ValueError):
            names.append(validate_interface_name(name))
    return names


def foreign_state() -> dict:
    """Every qdisc and filter NetTap doesn't own, per interface (clsact excluded: NetTap adds it)."""
    state = {}
    for iface in interfaces():
        try:
            qdiscs = json.loads(sh("tc", "-j", "qdisc", "show", "dev", iface) or "[]")
            kept = sorted(
                (q.get("kind"), q.get("handle"), q.get("parent"))
                for q in qdiscs
                if q.get("kind") != "clsact"
            )
            filters = []
            for hook in ("ingress", "egress"):
                with contextlib.suppress(RuntimeError):
                    dump = sh("tc", "-j", "filter", "show", "dev", iface, hook)
                    filters += sorted(
                        (hook, e.pref, e.protocol, e.handle, e.cookie)
                        for e in parse_filter_dump(dump)
                        if parse_cookie(e.cookie) is None
                    )
            state[iface] = (kept, filters)
        except (RuntimeError, ValueError) as exc:
            state[iface] = ("unreadable", str(exc))
    return state


def owned(iface: str) -> list:
    dump = sh("tc", "-j", "filter", "show", "dev", iface, "ingress")
    return [e for e in parse_filter_dump(dump) if parse_cookie(e.cookie)]


def lifecycle(mac: str) -> None:
    health = HealthWatch()
    health.start()
    try:
        before = foreign_state()
        snaps = []
        for _ in range(6):
            snaps.append(api(f"/api/live-bandwidth?mac={mac}"))
            time.sleep(2)
        status, snap = snaps[-1]
        if status != 200 or not snap.get("supported"):
            check(
                False,
                f"the meter runs for {mac}: {status} {snap.get('reason') or snap}",
            )
            return
        iface = snap["interface"]
        ticks = [
            s["samples"][-1]["tick"]
            for st, s in snaps
            if st == 200 and s.get("supported")
        ]
        check(
            len(ticks) == 6 and ticks[-1] > ticks[0],
            f"ticks advance on {iface}: {ticks}",
        )
        latest = snap["latest"]
        print(f"INFO  {mac}: down {latest['down_bps']} bit/s, up {latest['up_bps']} bit/s, "
              f"reason {latest['reason']!r}, offloads {snap['offloads']}", flush=True)  # fmt: skip
        check(len(owned(iface)) >= 2, "NetTap's filters are on the capture interface")
        print(
            "INFO  (close every device page while this runs: an open page keeps its watch)"
        )
        time.sleep(IDLE_WAIT_S)
        check(
            owned(iface) == [],
            f"{IDLE_WAIT_S} s after the last poll NetTap's filters are gone",
        )

        fakes = [f"02:4e:54:00:02:{n:02x}" for n in range(9)]
        results = [api(f"/api/live-bandwidth?mac={m}") for m in fakes]
        check(
            all(st == 200 and s.get("supported") for st, s in results[:8]),
            "eight devices can be watched at once",
        )
        status, body = results[8]
        check(
            status == 503 and "Too many" in body.get("error", ""),
            f"the ninth gets 503: {body}",
        )
        time.sleep(IDLE_WAIT_S)
        check(owned(iface) == [], "every watch cleaned itself up")
        after = foreign_state()
        changed = [i for i in before if i in after and before[i] != after[i]]
        check(
            not changed,
            f"no qdisc or filter NetTap doesn't own changed (changed: {changed})",
        )
    finally:
        health.stop()
    check(
        health.worst < 1.0, f"/api/health stayed under 1 s ({health.worst:.2f} s worst)"
    )


def main(argv: list[str]) -> int:
    mode = argv[0] if argv else ""
    if mode == "kernel":
        kernel()
    elif mode == "bench":
        bench()
    elif mode == "lifecycle":
        lifecycle(argv[1] if len(argv) > 1 else DEV_MAC)
    else:
        print(__doc__)
        return 2
    print(f"\n{sum(RESULTS)}/{len(RESULTS)} checks passed", flush=True)
    return 0 if RESULTS and all(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
