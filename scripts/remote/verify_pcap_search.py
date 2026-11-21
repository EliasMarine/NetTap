"""PCAP search checks on the device (NET-347), run inside nettap-storage-daemon.

deploy-live-audit-fixes.sh pipes this file to `python3 -` in the daemon container: the token
is read from its file there and never printed, and TShark is reached the way the daemon
reaches it (docker exec nettap-tshark). Standard library only. Exit 0 only when every check
passed.

1. A filter TShark refuses is refused by the filter check and by the search (400).
2. Known answer: for a 60 s window of closed captures, each listed file is counted with
   TShark directly, then the search must cover every file in full and report exactly those
   counts.
"""

import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

API = "http://localhost:8880"
BAD = "nettapqa_invalid_filter"
CLOSED_AFTER_S = (
    120  # a file not written for 2 minutes is not the one capture is filling
)
WINDOW_S = 60
WRITER_LAG_S = (
    45  # past the daemon's 30 s writer lag, so the file being written isn't listed
)
TRIES = 3
READ_TIMEOUT_S = 300  # one reference read, the same allowance as a search read
SEARCH_DEADLINE_S = 25 * 60
BUSY_TRIES = 6  # 503s are retried for up to 30 s
FAILED = []

TOKEN_FILE = "/run/nettap-auth/daemon-token"
TOKEN = ""  # read in main(), never printed


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(
        f"   {'✓' if ok else '✗'} {label}{': ' + detail if detail else ''}", flush=True
    )
    if not ok:
        FAILED.append(label)
    return ok


def call_once(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(
        API + path,
        data=None if body is None else json.dumps(body).encode(),
        method=method,
        headers={"X-NetTap-Daemon-Token": TOKEN, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as reply:
            return reply.status, json.load(reply)
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.load(exc)
        except ValueError:
            return exc.code, {}


def call(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    """A request, tried again while the daemon answers 503 (reader busy, or a start ran late)."""
    for _ in range(BUSY_TRIES):
        status, reply = call_once(method, path, body)
        if status != 503:
            break
        time.sleep(5)
    return status, reply


def query(**params: str) -> str:
    return "?" + urllib.parse.urlencode(params)


def refused_filter() -> None:
    print("→ A refused filter starts nothing")
    status, body = call("POST", "/api/pcap/check-filter", {"filter": BAD})
    check(
        "Filter check refuses it",
        status == 400 and BAD in body.get("error", ""),
        f"HTTP {status}",
    )
    status, body = call("GET", "/api/pcap/search" + query(filter=BAD))
    check(
        "Search refuses it",
        status == 400 and BAD in body.get("error", ""),
        f"HTTP {status}",
    )


def reference_count(relative_path: str, display_filter: str) -> int | None:
    """TShark's own count of matching frames, or None if the file wasn't read to the end."""
    try:
        run = subprocess.run(
            [
                "docker",
                "exec",
                "nettap-tshark",
                # ends TShark in the container too, not just the docker client
                "timeout",
                "-k",
                "5",
                str(READ_TIMEOUT_S),
                "tshark",
                "-r",
                f"/pcap/{relative_path}",
                "-Y",
                display_filter,
                "-T",
                "fields",
                "-e",
                "frame.number",
            ],
            check=False,
            capture_output=True,
            timeout=READ_TIMEOUT_S + 30,
        )
    except subprocess.TimeoutExpired:
        print(f"     {relative_path}: the reference read took over {READ_TIMEOUT_S} s")
        return None
    if run.returncode != 0:
        print(
            f"     {relative_path}: exit {run.returncode}: {run.stderr.decode(errors='replace').strip()[:200]}"
        )
        return None
    return run.stdout.count(b"\n")


def pick_window(end: datetime) -> tuple[str, str, list[dict]] | None:
    """The window ending at `end`, and its files, if every one of them is closed."""
    start = end - timedelta(seconds=WINDOW_S)
    span = {"from": start.isoformat(), "to": end.isoformat()}
    status, body = call("GET", "/api/pcap/files" + query(**span))
    files = body.get("files", []) if status == 200 else []
    cutoff = datetime.now(UTC) - timedelta(seconds=CLOSED_AFTER_S)
    if not files or any(datetime.fromisoformat(f["modified"]) > cutoff for f in files):
        return None
    return span["from"], span["to"], files


def known_answer() -> None:
    print("→ Known-answer search over closed captures")
    status, body = call("GET", "/api/pcap/files")
    cutoff = datetime.now(UTC) - timedelta(seconds=CLOSED_AFTER_S)
    closed = [
        f
        for f in body.get("files", [])
        if datetime.fromisoformat(f["modified"]) <= cutoff
    ]
    if not check(
        "Closed capture files to search",
        status == 200 and bool(closed),
        f"{len(closed)} found",
    ):
        return
    end = datetime.fromisoformat(closed[0]["modified"]) - timedelta(
        seconds=WRITER_LAG_S
    )
    for attempt in range(1, TRIES + 1):
        picked = pick_window(end)
        end -= timedelta(seconds=WINDOW_S)
        if picked is None:
            print(
                f"     window {attempt}: no files, or one still being written; trying an earlier one"
            )
            continue
        start_ts, end_ts, files = picked
        print(f"     window {attempt}: {start_ts} → {end_ts}, {len(files)} file(s)")
        for display_filter in ("udp", "frame"):
            counts = {
                f["file"]: reference_count(f["relative_path"], display_filter)
                for f in files
            }
            if None in counts.values() or any(counts.values()):
                break
        if None in counts.values() or not any(counts.values()):
            print(
                "     a file couldn't be read to the end, or holds no frames; trying an earlier window"
            )
            continue
        check(
            "Reference counts",
            True,
            f"{sum(counts.values())} {display_filter} frames in {len(files)} file(s)",
        )
        return compare(display_filter, start_ts, end_ts, counts)
    check("A usable window", False, f"none in {TRIES} tries")


def compare(
    display_filter: str, start_ts: str, end_ts: str, expected: dict[str, int]
) -> None:
    search = query(filter=display_filter, **{"from": start_ts, "to": end_ts})
    deadline = time.monotonic() + SEARCH_DEADLINE_S
    while True:
        status, body = call("GET", "/api/pcap/search" + search)
        if status != 200 or body.get("complete") or time.monotonic() > deadline:
            break
        time.sleep(5)
    if not check(
        "Search finished",
        status == 200 and body.get("complete") is True,
        f"HTTP {status}",
    ):
        return
    total = len(expected)
    covered = (body["files_checked"], body["files_full"], body["files_total"])
    check(
        "Every file read in full",
        covered == (total, total, total),
        f"checked/full/total {covered}, expected {total}",
    )
    check(
        "No file failed or timed out",
        body["failed"] == 0 and body["timed_out"] == 0,
        f"failed {body['failed']}, timed out {body['timed_out']}, {body.get('error') or 'no error'}",
    )
    found = {r["file"]: r["matching_packets"] for r in body["results"]}
    wanted = {f: n for f, n in expected.items() if n}
    check(
        "Counts match TShark's own",
        found == wanted,
        f"search {found} vs reference {wanted}",
    )


def main() -> int:
    global TOKEN
    with open(TOKEN_FILE) as fh:
        TOKEN = fh.read().strip()
    refused_filter()
    known_answer()
    print(f"   {'all checks passed' if not FAILED else 'FAILED: ' + ', '.join(FAILED)}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
