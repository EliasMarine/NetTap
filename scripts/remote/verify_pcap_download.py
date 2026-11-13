"""
NET-189 device check for PCAP Search's "Download filtered". Runs inside the daemon container
(root, docker CLI, host network):

  sudo docker exec -i nettap-storage-daemon python3 - < scripts/remote/verify_pcap_download.py

It sends the request the page's download window sends (from/to as the browser's toISOString())
for a 4 s window around the first packet of a recent capture file, so the window spans two
files, and reads the streamed capture with capinfos in nettap-tshark. Then it checks a second
download is turned away while one runs, and the page's default request (last hour, dns).

One PASS/FAIL line per check; exit 0 only when every check passed. The daemon token is read from
its volume and never printed.
"""

import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from decimal import Decimal

API = "http://localhost:8880"
TOKEN_PATH = "/run/nettap-auth/daemon-token"
TSHARK = "nettap-tshark"
HALF_WINDOW = Decimal(2)  # files rotate every 5-60 s on the G11
MAX_PACKETS = 400_000  # the download's budget (services/pcap_search.py)
CHUNK = 64 * 1024
BUSY_TRIES = 10
BUSY_WAIT_S = 3
LEFT_TRIES = 15

RESULTS: list[bool] = []


def check(ok: bool, what: str) -> None:
    RESULTS.append(bool(ok))
    print(("PASS  " if ok else "FAIL  ") + what, flush=True)


def iso(epoch: Decimal) -> str:
    """Epoch seconds as the page sends them: toISOString(), whole milliseconds, Z."""
    ms = int(epoch * 1000)
    return datetime.fromtimestamp(ms // 1000, UTC).strftime("%Y-%m-%dT%H:%M:%S") + (
        f".{ms % 1000:03d}Z"
    )


def request(path: str, timeout: float = 300):
    """The daemon's response (urllib's, or its HTTPError); the token never leaves here."""
    with open(TOKEN_PATH) as handle:
        token = handle.read().strip()
    req = urllib.request.Request(API + path, headers={"X-NetTap-Daemon-Token": token})
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        return exc


def request_when_free(path: str):
    """`request`, waiting out a 503: the previous download's job still being stopped, or the
    index catching up just after the daemon restarted."""
    for _ in range(BUSY_TRIES - 1):
        resp = request(path)
        if resp.status != 503:
            return resp
        print(f"INFO  busy ({resp.read(200)!r}), trying again", flush=True)
        time.sleep(BUSY_WAIT_S)
    return request(path)


def get_json(path: str) -> tuple[int, dict]:
    resp = request(path, timeout=120)
    try:
        return resp.status, json.load(resp)
    except ValueError:
        return resp.status, {}


def download_path(filt: str, start: Decimal, end: Decimal) -> str:
    query = urllib.parse.urlencode({"filter": filt, "from": iso(start), "to": iso(end)})
    return f"/api/pcap/download?{query}"


def pick_window(
    rows: list[dict],
) -> tuple[Decimal, Decimal, Decimal, list[dict]] | None:
    """(from, to, file B's first packet, files overlapping) for the newest settled file B whose
    4 s window around its first packet spans at least two files within the budget."""
    indexed = sorted(
        (r for r in rows if r.get("state") == "indexed" and r.get("first")),
        key=lambda r: Decimal(r["first"]),
        reverse=True,
    )
    for b in indexed[1:]:  # the newest file may still be written
        first = Decimal(b["first"])
        start, end = first - HALF_WINDOW, first + HALF_WINDOW
        start = Decimal(int(start * 1000)) / 1000  # the page's millisecond bounds
        end = Decimal(int(end * 1000)) / 1000
        over = [
            r
            for r in indexed
            if Decimal(r["first"]) < end and Decimal(r["last"]) >= start
        ]
        if len(over) >= 2 and sum(r["packets"] for r in over) <= MAX_PACKETS:
            return start, end, first, over
    return None


def parse_capinfos(text: str) -> tuple[int, Decimal, Decimal] | None:
    """(packets, first, last) from `capinfos -a -e -c -E -S -M -T -` (the index's flags)."""
    lines = text.splitlines()
    for i, line in enumerate(lines[:-1]):
        if line.startswith("File name\t"):
            row = lines[i + 1].rsplit("\t", 4)
            try:
                return int(row[2]), Decimal(row[3]), Decimal(row[4])
            except (IndexError, ValueError, ArithmeticError):
                return None
    return None


def read_capture(resp) -> tuple[int, Decimal, Decimal] | None:
    """Stream a response body into capinfos in the tshark container."""
    proc = subprocess.Popen(
        ["docker", "exec", "-i", TSHARK, "capinfos", "-a", "-e", "-c", "-E", "-S", "-M", "-T", "-"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )  # fmt: skip
    try:
        while chunk := resp.read(CHUNK):
            proc.stdin.write(chunk)
    finally:
        proc.stdin.close()
    out = proc.stdout.read().decode("utf-8", "replace")
    proc.wait(timeout=60)
    return parse_capinfos(out)


def tshark_tmp() -> tuple[str, list[str]]:
    """nettap-tshark's /tmp: KiB used, and what a download could leave there (its window
    cut's FIFOs, the old merge's file)."""

    def run(*argv: str) -> str:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        return done.stdout

    df = run("docker", "exec", TSHARK, "df", "-P", "/tmp").splitlines()
    names = run("docker", "exec", TSHARK, "ls", "-A", "/tmp").split()
    left = [n for n in names if n.startswith("nt-") or n == "nettap_merged.pcap"]
    return (df[-1].split()[2] if len(df) > 1 else "unknown"), left


def nothing_left(start_used: str) -> None:
    """Every download above, finished, refused or stopped mid-stream, left /tmp as it was."""
    for _ in range(LEFT_TRIES):  # a stopped job's group is killed a moment later
        used, left = tshark_tmp()
        if used == start_used and not left:
            break
        time.sleep(1)
    check(used == start_used and not left,
          f"nettap-tshark /tmp as it started: {used} KiB used (was {start_used}), "
          f"left over: {left or 'nothing'}")  # fmt: skip


def straddling_download(start: Decimal, end: Decimal, b_first: Decimal, over) -> None:
    names = [r["name"] for r in over]
    print(f"INFO  window {iso(start)} .. {iso(end)}: {len(over)} files {names}, "
          f"{sum(r['packets'] for r in over)} packets, file B starts {b_first}", flush=True)  # fmt: skip
    query = urllib.parse.urlencode({"from": iso(start), "to": iso(end)})
    status, listed = get_json(f"/api/pcap/files?{query}")
    shown = {f.get("name") for f in listed.get("files", [])}
    check(status == 200 and set(names) <= shown,
          f"the file list for the window shows every file holding it ({status})")  # fmt: skip
    started = time.monotonic()
    resp = request_when_free(download_path("tcp", start, end))
    if resp.status != 200:
        check(False, f"download of the window: {resp.status} {resp.read()[:300]!r}")
        return
    try:
        got = read_capture(resp)
    except (OSError, urllib.error.URLError) as exc:  # the daemon aborted part-way
        check(False, f"download of the window broke off: {exc}")
        return
    seconds = time.monotonic() - started
    if got is None:
        check(False, "capinfos could not read the downloaded capture")
        return
    packets, first, last = got
    print(
        f"INFO  {packets} tcp packets, {first} .. {last}, {seconds:.1f} s", flush=True
    )
    check(packets > 0, "the download holds packets")
    check(start <= first and last < end, "every packet is inside the window")
    check(first < b_first <= last, "it holds packets from both sides of file B's start")


def second_download_is_busy(start: Decimal, end: Decimal) -> None:
    """A download whose reader doesn't read holds the lock; a second one gets 503. All frames
    of the window, so the body is larger than the socket buffers."""
    first = request(download_path("frame", start, end))
    if first.status != 200:
        check(False, f"the first download started: {first.status}")
        return
    try:
        first.read(CHUNK)  # then stop reading: back-pressure keeps its job running
        second = request(download_path("frame", start, end))
        body = second.read(300)
        check(second.status == 503 and b"Another download is running" in body,
              f"a second download while one runs: {second.status} {body!r}")  # fmt: skip
    finally:
        first.close()  # the daemon's write fails and its job is killed


def page_default() -> None:
    end = Decimal(time.time())
    resp = request_when_free(download_path("dns", end - 3600, end))
    if resp.status == 400:
        reason = json.load(resp).get("error", "")
        check(
            "packets" in reason,
            f"the last hour is over the budget and says so: {reason}",
        )
        return
    if resp.status != 200:
        check(
            False, f"the page's default download: {resp.status} {resp.read()[:300]!r}"
        )
        return
    got = read_capture(resp)
    inside = got is not None and (
        got[0] == 0 or (end - 3600 <= got[1] and got[2] < end)
    )
    check(inside, f"the page's default download (last hour, dns) is a readable capture "
          f"inside the hour: {got}")  # fmt: skip


def main() -> int:
    start_used, left = tshark_tmp()
    check(not left, f"nettap-tshark /tmp holds nothing from earlier downloads: {left}")
    status, body = get_json("/api/packets/captures")
    window = pick_window(body.get("files", [])) if status == 200 else None
    if window is None:
        check(
            False,
            f"a recent capture file with a neighbour inside the budget ({status})",
        )
    else:
        straddling_download(*window)
        second_download_is_busy(*window[:2])
    page_default()
    nothing_left(start_used)
    print(f"\n{sum(RESULTS)}/{len(RESULTS)} checks passed", flush=True)
    return 0 if RESULTS and all(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
