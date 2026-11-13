"""
NET-205 release gate for the live bandwidth meter. Runs inside the daemon container (root,
NET_ADMIN, NET_RAW, host network), where the meter's own code is importable:

  sudo docker exec -i nettap-storage-daemon python3 - kernel < scripts/remote/verify_live_bandwidth.py
  sudo docker exec -i nettap-storage-daemon python3 - bench < scripts/remote/verify_live_bandwidth.py
  sudo docker exec -i nettap-storage-daemon python3 - lifecycle [MAC] < scripts/remote/verify_live_bandwidth.py
  sudo docker exec -i nettap-storage-daemon python3 - off < scripts/remote/verify_live_bandwidth.py
  sudo docker exec -i nettap-storage-daemon python3 - capture-safety < scripts/remote/verify_live_bandwidth.py

kernel          the meter's own filter lines, on a throwaway veth pair, count known frames exactly
bench           the filters' per-packet cost on the veth pair: interleaved paired rounds of no
                clsact, one MAC watch, one IP watch and eight watches; the median difference and
                its spread, as ns per frame and % of one core at 1 Gbit/s (stated, not pass/fail)
lifecycle       the API on the capture interface: start, idle stop, the cap, nothing foreign touched
                (needs the setting on)
off             the setting: off means no counters and an off reply; turning off with eight
                watches removes every NetTap filter within 10 s (leaves the setting off)
capture-safety  NIC drops and Suricata's kernel drops (needs NET-206's counters) with the meter
                off vs eight watches, alternating 60 s arms, while a sustained download runs on the
                dev Mac (puts the owner's setting back)

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
    TcError,
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
BENCH_ROUNDS = 7
MIXES = {"min": [60], "imix": [60] * 7 + [590] * 4 + [1514], "full": [1514]}
API = "http://localhost:8880"
SETTING = "/api/settings/live-bandwidth"
TOKEN_PATH = "/run/nettap-auth/daemon-token"
SYS_NET = os.environ.get("HOST_SYS_NET", "/host/sys/class/net")
DEV_MAC = "bc:89:c1:e1:8a:d6"  # the dev Mac on the G11's mirrored link
IDLE_WAIT_S = 20
CLEAN_WITHIN_S = 10
# eight devices that don't exist
FAKE_MACS = [f"02:4e:54:00:03:{n:02x}" for n in range(8)]
ARM_S = 60
PAIRS = 3
SURICATA = "nettap-suricata-live"
SURICATA_SOCKET = "/var/run/suricata/suricata-command.socket"
STATS_SYNC_S = 10  # SURICATA_STATS_INTERVAL in docker/docker-compose.yml (NET-206)
# An eight-watch arm counts as worse only by more than this many drops: one stray drop on
# either arm would otherwise decide the pair
NOISE_DROPS = 10
DROPS = ("rx_dropped", "rx_missed_errors", "rx_fifo_errors")

RESULTS: list[bool] = []


def check(ok: bool, what: str) -> None:
    RESULTS.append(bool(ok))
    print(("PASS  " if ok else "FAIL  ") + what, flush=True)


def sh(*argv: str, stdin: str | None = None) -> str:
    done = subprocess.run(
        argv, input=stdin, capture_output=True, text=True, timeout=30, check=False
    )
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


# traffic hits the watched MAC and IP, like a real device
ARMS: dict[str, list[Key]] = {
    "none": [],
    "one MAC watch": [Key("mac", TEST_MAC)],
    "one IP watch": [Key("ip", TEST_IP)],
    "eight watches": [Key("mac", TEST_MAC)]
    + [Key("mac", f"02:4e:54:00:01:{n:02x}") for n in range(3)]
    + [Key("ip", TEST_IP)]
    + [Key("ip", f"192.0.2.{100 + n}") for n in range(3)],
}


def configure(keys: list[Key]) -> None:
    with contextlib.suppress(RuntimeError):
        sh("tc", "qdisc", "del", "dev", B, "clsact")
    if keys:
        sh("tc", "qdisc", "add", "dev", B, "clsact")
        add(
            [
                line
                for slot, key in enumerate(keys)
                for line in build_filter_lines(B, key, slot, 1)
            ]
        )


def measure(sock, frames: list[bytes], cpu: int) -> tuple[float, float]:
    """(CPU ns, wall ns) per frame the peer received.

    CPU: system + irq + softirq on the pinned CPU. Wall: the send loop's elapsed time, which holds
    the delivery too (veth delivers in the sender's softirq) and isn't rounded to clock ticks.
    """
    rounds = BENCH_FRAMES // len(frames)
    rx0, c0, t0 = rx_packets(), cpu_ticks(cpu), time.perf_counter_ns()
    for _ in range(rounds):
        for data in frames:
            sock.send(data)
    t1, c1 = time.perf_counter_ns(), cpu_ticks(cpu)
    received = max(rx_packets() - rx0, 1)
    return (c1 - c0) * 1e9 / os.sysconf("SC_CLK_TCK") / received, (t1 - t0) / received


def paired_rounds(
    sock, frames: list[bytes], cpu: int
) -> dict[str, list[tuple[float, float]]]:
    """Each arm's (CPU, wall) cost over "none" from the same round, for BENCH_ROUNDS rounds."""
    names, diffs = list(ARMS), {name: [] for name in ARMS if name != "none"}
    for r in range(BENCH_ROUNDS):
        cost = {}
        shift = r % len(names)  # no arm always runs first
        for name in names[shift:] + names[:shift]:
            configure(ARMS[name])
            cost[name] = measure(sock, frames, cpu)
        for name, series in diffs.items():
            series.append(
                (cost[name][0] - cost["none"][0], cost[name][1] - cost["none"][1])
            )
    return diffs


def spread_text(diffs: list[float], pps: float) -> tuple[str, bool]:
    """'median [quartiles] ns = share [quartiles] of one core', and whether it's unstable."""
    q1, median, q3 = statistics.quantiles(diffs, n=4)
    share = [v * pps / 1e9 for v in (median, q1, q3)]
    text = f"{median:+.0f} ns [{q1:+.0f}..{q3:+.0f}] = {share[0]:.1%} [{share[1]:.1%}..{share[2]:.1%}]"
    return text, q3 - q1 > median


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
                pps = line_rate_pps(sizes)
                print(f"INFO  {name}: {BENCH_ROUNDS} paired rounds, cost over no clsact as the "
                      f"median [quartiles] per frame = share of one core at 1 Gbit/s "
                      f"({pps:,.0f} frames/s)", flush=True)  # fmt: skip
                for arm, series in paired_rounds(sock, frames, cpu).items():
                    cpu_text, cpu_bad = spread_text([c for c, _ in series], pps)
                    wall_text, wall_bad = spread_text([w for _, w in series], pps)
                    flag = (
                        "  UNSTABLE: spread > median, rerun or quote a range"
                        if cpu_bad or wall_bad
                        else ""
                    )
                    print(
                        f"INFO    {arm:<14} CPU {cpu_text}   wall {wall_text}{flag}",
                        flush=True,
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
        # not _stop: that shadows Thread._stop and breaks join()
        self._halt = threading.Event()

    def run(self) -> None:
        while not self._halt.wait(0.5):
            start = time.monotonic()
            try:
                urllib.request.urlopen(API + "/api/health", timeout=5).read()
                self.worst = max(self.worst, time.monotonic() - start)
            except OSError:
                self.worst = max(self.worst, 99.0)

    def stop(self) -> None:
        self._halt.set()
        self.join()


def api(path: str, body: dict | None = None) -> tuple[int, dict]:
    """GET path, or PUT body to it, with the daemon token (never printed)."""
    with open(TOKEN_PATH) as handle:
        token = handle.read().strip()
    request = urllib.request.Request(
        API + path,
        data=None if body is None else json.dumps(body).encode(),
        method="GET" if body is None else "PUT",
        headers={"X-NetTap-Daemon-Token": token, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)


def interfaces() -> list[str]:
    names = []
    for name in sorted(os.listdir(SYS_NET)):
        if not os.path.isdir(os.path.join(SYS_NET, name)):  # bonding_masters is a file
            continue
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
        # TcError: a dump we can't parse
        except (RuntimeError, ValueError, TcError) as exc:
            state[iface] = ("unreadable", str(exc))
    return state


def owned(iface: str) -> list:
    dump = sh("tc", "-s", "-j", "filter", "show", "dev", iface, "ingress")
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


# ---------------------------------------------------------------------------- off


def set_setting(on: bool) -> tuple[int, dict]:
    return api(SETTING, {"enabled": on})


def wait_clean(iface: str | None) -> tuple[bool, float]:
    """Wait up to CLEAN_WITHIN_S for clean-up idle and no NetTap filter on iface (when given)."""
    start = time.monotonic()
    while True:
        status, setting = api(SETTING)
        idle = status == 200 and (setting.get("cleanup") or {}).get("state") == "idle"
        if idle and (iface is None or not owned(iface)):
            return True, time.monotonic() - start
        if time.monotonic() - start >= CLEAN_WITHIN_S:
            return False, time.monotonic() - start
        time.sleep(0.5)


def owned_anywhere() -> dict:
    """NetTap filters per interface that has any; one we can't read counts unless it vanished."""
    found: dict = {}
    for iface in interfaces():
        try:
            if count := len(owned(iface)):
                found[iface] = count
        except (RuntimeError, TcError) as exc:
            if os.path.exists(os.path.join(SYS_NET, iface)):
                found[iface] = f"unreadable: {exc}"
    return found


def is_off(reply: tuple[int, dict]) -> bool:
    return reply[0] == 200 and reply[1].get("off") is True


def off_gate() -> None:
    status, reply = set_setting(False)
    check(
        status == 200 and reply.get("enabled") is False,
        f"the setting turns off ({status})",
    )
    ok, took = wait_clean(None)
    check(ok, f"clean-up is idle with the setting off ({took:.1f} s)")
    probe = api(f"/api/live-bandwidth?mac={FAKE_MACS[0]}")
    check(is_off(probe), f"a device page gets the off reply: {probe}")
    left = owned_anywhere()
    check(not left, f"no NetTap filter on any interface while off ({left or 'none'})")

    status, reply = set_setting(True)
    check(
        status == 200 and reply.get("enabled") is True,
        f"the setting turns on ({status})",
    )
    replies = [api(f"/api/live-bandwidth?mac={mac}") for mac in FAKE_MACS]
    started = [body for code, body in replies if code == 200 and body.get("supported")]
    check(
        len(started) == 8,
        f"eight watches start ({len(started)}/8; first reply {replies[0]})",
    )
    if not started:
        return
    iface = started[0]["interface"]
    time.sleep(2)
    for mac in FAKE_MACS:  # the keepalive of eight open device pages
        api(f"/api/live-bandwidth?mac={mac}")
    count = len(owned(iface))
    check(count >= 16, f"their filters are on {iface} ({count}, two per watch)")

    start = time.monotonic()
    status, reply = set_setting(False)
    print(f"INFO  turning off answered in {time.monotonic() - start:.2f} s, "
          f"clean-up {reply.get('cleanup')}", flush=True)  # fmt: skip
    check(
        status == 200 and reply.get("enabled") is False,
        f"the setting turns off ({status})",
    )
    ok, took = wait_clean(iface)
    check(ok, f"every NetTap filter on {iface} is gone and clean-up idle within "
          f"{CLEAN_WITHIN_S} s ({took:.1f} s)")  # fmt: skip
    probe = api(f"/api/live-bandwidth?mac={FAKE_MACS[0]}")
    check(is_off(probe), f"a keepalive after the turn-off gets the off reply: {probe}")
    left = owned_anywhere()
    check(not left, f"no NetTap filter on any interface ({left or 'none'})")
    print("INFO  the setting is left off", flush=True)


# ---------------------------------------------------------------------------- capture-safety


def nic_counters(iface: str) -> dict[str, int]:
    counters = {}
    for name in (*DROPS, "rx_bytes"):
        with open(os.path.join(SYS_NET, iface, "statistics", name)) as handle:
            counters[name] = int(handle.read())
    return counters


def capture_verdict(pairs: list[tuple[float, float]]) -> str:
    """PASS when no eight-watch arm dropped more than NOISE_DROPS over its off arm, FAIL when
    every pair did, INCONCLUSIVE when it's mixed (rerun). Pairs are (off, eight) drops."""
    # OLD CODE START — NET-206 review: no noise margin, so one drop decided a pair
    # worse = [eight > off for off, eight in pairs]
    # OLD CODE END
    worse = [eight - off > NOISE_DROPS for off, eight in pairs]
    if not any(worse):
        return "PASS"
    return "FAIL" if all(worse) else "INCONCLUSIVE"


def parse_counters(out: str) -> tuple[int, int, int]:
    """(uptime, capture.kernel_packets, capture.kernel_drops) from a dump-counters answer."""
    try:
        answer = json.loads(out.replace("\n", ""))
    except ValueError as exc:
        raise RuntimeError(
            f"Suricata's dump-counters answer isn't JSON: {exc}"
        ) from exc
    if answer.get("return") != "OK":
        raise RuntimeError(
            f"Suricata's counters aren't available ({answer.get('message')}): deploy NET-206"
        )
    stats = answer.get("message") or {}
    capture = stats.get("capture") or {}
    try:
        return (
            int(stats["uptime"]),
            int(capture["kernel_packets"]),
            int(capture["kernel_drops"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"dump-counters has no usable {exc}") from exc


def suricata_capture() -> tuple[int, int, int]:
    return parse_counters(
        sh("docker", "exec", SURICATA, "suricatasc", SURICATA_SOCKET, "-c", "dump-counters")
    )  # fmt: skip


def arm_delta(
    before: tuple[int, int, int],
    after: tuple[int, int, int],
    number: int,
    seconds: float,
) -> tuple[int, int]:
    """Suricata's (packets, drops) over one arm of `seconds`. A restart voids the arm: its uptime
    grew by less than the arm (less one sync), or a counter went down. No packets means no
    load, so no result."""
    packets, drops = after[1] - before[1], after[2] - before[2]
    # OLD CODE START — NET-206 review: missed a restart when Suricata's uptime was shorter
    # than the arm at its start
    # if after[0] < before[0] or packets < 0 or drops < 0:
    # OLD CODE END
    restarted = after[0] - before[0] < seconds - STATS_SYNC_S
    if restarted or packets < 0 or drops < 0:
        raise RuntimeError(f"Suricata restarted during arm {number}: rerun")
    if packets == 0:
        raise RuntimeError(
            f"Suricata saw no packets in arm {number}: is the download running?"
        )
    return packets, drops


def poll_all(macs: list[str]) -> None:
    """Start or keep alive one watch per MAC (a watch only lives while its page polls)."""
    for mac in macs:
        code, body = api(f"/api/live-bandwidth?mac={mac}")
        if code != 200 or not body.get("supported"):
            raise RuntimeError(f"the watch on {mac} isn't running: {code} {body}")


# OLD CODE START — NET-206: the arm also measures Suricata's kernel counters
# def run_arm(arm: str, iface: str, number: int) -> int:
#     """One ARM_S arm, meter off or eight watches; returns the growth of the NIC's drop counters."""
# OLD CODE END
def run_arm(arm: str, iface: str, number: int) -> tuple[int, int, int]:
    """One ARM_S arm, meter off or eight watches; returns the growth of the NIC's drop counters
    and Suricata's (packets, drops) over the arm."""
    macs = [DEV_MAC] + FAKE_MACS[:7] if arm == "eight" else []
    status, _ = set_setting(bool(macs))
    if status != 200:
        raise RuntimeError(f"the setting didn't change ({status})")
    if not macs and not wait_clean(iface)[0]:
        raise RuntimeError(f"the counters weren't removed within {CLEAN_WITHIN_S} s")
    poll_all(macs)  # every watch is installed before the counters are read
    label = "eight watches" if macs else "meter off"
    print(f"INFO  {time.strftime('%H:%M:%S')} arm {number}: {label} for {ARM_S} s "
          "(keep the download running)", flush=True)  # fmt: skip
    # Suricata refreshes its totals every STATS_SYNC_S: wait one sync, so both readings are of
    # this arm
    settle = time.monotonic() + STATS_SYNC_S + 1
    while (left := settle - time.monotonic()) > 0:
        time.sleep(min(2.0, left))
        poll_all(macs)
    before, start = nic_counters(iface), time.monotonic()
    suricata_before = suricata_capture()
    while (left := start + ARM_S - time.monotonic()) > 0:
        time.sleep(min(2.0, left))
        poll_all(macs)
    after, seconds = nic_counters(iface), time.monotonic() - start
    packets, drops = arm_delta(suricata_before, suricata_capture(), number, seconds)
    growth = {name: after[name] - before[name] for name in DROPS}
    rate = (after["rx_bytes"] - before["rx_bytes"]) * 8 / seconds / 1e6
    print(
        f"INFO    {label}: {rate:.0f} Mbit/s received on {iface}, drops grew {growth}; "
        f"Suricata {packets} packets, {drops} dropped ({100 * drops / packets:.3f}%)",
        flush=True,
    )
    return sum(growth.values()), packets, drops


def capture_safety() -> None:
    status, original = api(SETTING)
    if status != 200:
        check(False, f"the setting can be read: {status} {original}")
        return
    try:
        set_setting(True)
        code, snap = api(f"/api/live-bandwidth?mac={DEV_MAC}")
        if code != 200 or not snap.get("supported"):
            check(
                False,
                f"the meter runs for {DEV_MAC}: {code} {snap.get('reason') or snap}",
            )
            return
        iface = snap["interface"]
        suricata_capture()  # preflight: the counters are on (NET-206)
        print(f"INFO  {PAIRS} pairs of {ARM_S} s arms on {iface}, about "
              f"{PAIRS * 2 * (ARM_S + STATS_SYNC_S + 6) // 60 + 1} minutes. Start a sustained "
              "download on the dev Mac now and keep it running until the verdict.",
              flush=True)  # fmt: skip
        pairs, suricata_pairs = [], []
        totals = {"off": [0, 0], "eight": [0, 0]}
        # ABA order, so a drift over the run doesn't favour one arm
        for pair in range(PAIRS):
            order = ("off", "eight") if pair % 2 == 0 else ("eight", "off")
            grew = {
                arm: run_arm(arm, iface, 2 * pair + n + 1)
                for n, arm in enumerate(order)
            }
            pairs.append((grew["off"][0], grew["eight"][0]))
            # arms differ in length by up to one sync: the off arm's drops are scaled to the
            # eight-watch arm's packets
            (_, off_p, off_d), (_, eight_p, eight_d) = grew["off"], grew["eight"]
            suricata_pairs.append((off_d * eight_p / off_p, eight_d))
            for arm in order:
                totals[arm][0] += grew[arm][1]
                totals[arm][1] += grew[arm][2]
        verdict = capture_verdict(pairs)
        print(f"INFO  drops grew (off, eight watches) per pair: {pairs}", flush=True)
        check(verdict == "PASS", f"capture safety: {verdict}"
              + (" (mixed: rerun)" if verdict == "INCONCLUSIVE" else ""))  # fmt: skip
        for arm, (packets, drops) in totals.items():
            print(f"INFO  Suricata, {arm}: {packets} packets, {drops} dropped "
                  f"({100 * drops / packets:.3f}%)", flush=True)  # fmt: skip
        print(f"INFO  Suricata drops per pair (off scaled, eight watches): "
              f"{[(round(o, 1), e) for o, e in suricata_pairs]}", flush=True)  # fmt: skip
        suricata_verdict = capture_verdict(suricata_pairs)
        check(suricata_verdict == "PASS", f"Suricata capture loss: {suricata_verdict}"
              + (" (mixed: rerun)" if suricata_verdict == "INCONCLUSIVE" else ""))  # fmt: skip
    except (OSError, RuntimeError) as exc:
        check(False, f"capture safety could not finish: {exc}")
    finally:
        status, _ = set_setting(bool(original.get("enabled")))
        print(f"INFO  the setting is back {'on' if original.get('enabled') else 'off'} "
              f"({status})", flush=True)  # fmt: skip


def main(argv: list[str]) -> int:
    mode = argv[0] if argv else ""
    if mode == "kernel":
        kernel()
    elif mode == "bench":
        bench()
    elif mode == "lifecycle":
        lifecycle(argv[1] if len(argv) > 1 else DEV_MAC)
    elif mode == "off":
        off_gate()
    elif mode == "capture-safety":
        capture_safety()
    else:
        print(__doc__)
        return 2
    print(f"\n{sum(RESULTS)}/{len(RESULTS)} checks passed", flush=True)
    return 0 if RESULTS and all(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
