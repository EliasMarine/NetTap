"""Check packet analysis (NET-188) against an independent reading of the capture files.

Runs INSIDE the daemon container (deploy-packet-analysis.sh pipes it in):
    sudo docker exec -i nettap-storage-daemon python3 - < scripts/remote/verify-packet-analysis.py

It calls the daemon's real routes, then checks their answers a different way:
  1. Waits for the capture index to finish (backfill after the first deploy).
  2. Three random indexed files: the index's first and last packet times against a fresh capinfos.
  3. A 60 s window across a file boundary, `tcp.flags.syn == 1`: the files the search read
     against a fresh capinfos of every candidate file, and its rows against each of those files
     read whole by TShark with a time filter (no mergecap, no editcap), compared as
     (time, length, MD5).
  4. The download of that search, read back by TShark: the same (time, length, MD5) rows.
  5. One packet's detail: the same time and MD5 as its row.
  6. Field suggestions, the filter check (refused and accepted), and a hostile filter.
  7. A search over the last 60 s says its result is provisional.
  8. No job is left running in nettap-tshark.
Read-only. Exits 1 on any failure.
"""

import itertools
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = "/opt/nettap/pcap"
FAILED = False


def check(label: str, ok: bool, detail: str) -> None:
    global FAILED
    print(f"   {'✓' if ok else '✗'} {label}: {detail}", flush=True)
    FAILED = FAILED or not ok


def api(method: str, path: str, body: dict | None = None, raw: bool = False):
    with open("/run/nettap-auth/daemon-token") as fh:
        token = fh.read().strip()
    req = urllib.request.Request(
        "http://localhost:8880" + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={"X-NetTap-Daemon-Token": token, "Content-Type": "application/json"},
        method=method,
    )
    del token
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
            return r.status, data if raw else json.loads(data)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except ValueError:
            return e.code, {}


def tshark_container(args: list[str], stdin: bytes | None = None) -> str:
    """Run a command in nettap-tshark; stdout as text."""
    p = subprocess.run(
        ["docker", "exec", "-i", "nettap-tshark", *args],
        check=False,
        input=stdin,
        capture_output=True,
        timeout=600,
    )
    return p.stdout.decode("utf-8", "replace")


def capinfos(file_id: str) -> tuple[str, str] | None:
    out = tshark_container(
        ["capinfos", "-a", "-e", "-S", "-M", "-T", "-r", "--", f"/pcap/{file_id}"]
    )
    for line in out.splitlines():
        cols = line.rsplit("\t", 2)
        if len(cols) == 3 and cols[1] != "n/a":
            return cols[1], cols[2]
    return None


def dec(s: str) -> float:
    return float(s)


def same_time(a: str, b: str) -> bool:
    """Equal epoch times, compared as exact decimals (capinfos prints 6 places, TShark 9)."""

    def ns(v: str) -> int:
        whole, _, frac = v.partition(".")
        return int(whole) * 10**9 + int(frac.ljust(9, "0")[:9])

    return ns(a) == ns(b)


def step(title: str) -> None:
    print(f"\n→ {title}", flush=True)


# 1 -----------------------------------------------------------------------------
step("Check 1: the capture index finishes (first deploy backfills every file)")
for i in range(90):
    code, caps = api("GET", "/api/packets/captures")
    if code == 200 and caps["unindexed"] <= 8:
        break
    print(
        f"   indexing… {caps.get('unindexed', '?')} files left ({i + 1}/90)", flush=True
    )
    time.sleep(10)
check(
    "index ready",
    code == 200 and caps["unindexed"] <= 8,
    f"{caps.get('count')} files, {caps.get('unindexed')} not indexed yet, {caps.get('failed')} unreadable",
)
failed_files = [f for f in caps.get("files", []) if f["state"] == "failed"]
for f in failed_files[:5]:
    print(f"     unreadable: {f['id']}: {f['error']}")
cut = [f["id"] for f in caps.get("files", []) if f.get("cut_short")]
print(f"     cut short (last packet partly written): {len(cut)} {cut[:3]}")

# 2 -----------------------------------------------------------------------------
step("Check 2: index times against a fresh capinfos (3 random files)")
indexed = [
    f
    for f in caps["files"]
    if f["state"] == "indexed" and not f["recent"] and f["first"]
]
for f in random.sample(indexed, min(3, len(indexed))):
    fresh = capinfos(f["id"])
    ok = (
        fresh is not None
        and same_time(fresh[0], f["first"])
        and same_time(fresh[1], f["last"])
    )
    check(f"index {f['id']}", ok, f"index {f['first']}..{f['last']}, capinfos {fresh}")

# 3 -----------------------------------------------------------------------------
step("Check 3: a 60 s window across a file boundary, against each file read whole")
old = [f for f in indexed if dec(f["last"]) < time.time() - 600]
old.sort(key=lambda f: dec(f["first"]))
pair = None
for a, b in zip(old[-60:], old[-59:]):
    if dec(a["last"]) >= dec(b["first"]) - 30:
        pair = (a, b)
if pair is None:
    check("boundary window", False, "no two consecutive settled files found")
    sys.exit(1)
boundary = int(dec(pair[1]["first"]))
start, end = str(boundary - 30), str(boundary + 30)
filt = "tcp.flags.syn == 1"
t0 = time.time()
code, res = api(
    "POST",
    "/api/packets/search",
    {"filter": filt, "from": start, "to": end, "limit": 1000},
)
took = time.time() - t0
check(
    "search answered",
    code == 200,
    f"HTTP {code} in {took:.1f} s: {res.get('error', res.get('termination'))}",
)
if code != 200:
    sys.exit(1)
print(
    f"     window {start}..{end}, {len(res['rows'])} rows, termination {res['termination']}, "
    f"files {[f['id'] for f in res['files']]}"
)

# Independent file choice: every file that could hold the window, by a fresh capinfos
candidates: list[str] = []
for fid in {f["id"] for f in caps["files"]} | {
    e.name for e in os.scandir(ROOT) if e.is_file()
}:
    try:
        st = os.stat(os.path.join(ROOT, fid))
    except OSError:
        continue
    m = re.search(r"_(\d+)\.pcap", fid)
    if st.st_mtime >= int(start) - 60 and (not m or int(m.group(1)) <= int(end) + 60):
        candidates.append(fid)
holding = []
for fid in candidates:
    b = capinfos(fid)
    if b and dec(b[0]) < int(end) and dec(b[1]) >= int(start):
        holding.append(fid)
check(
    "files read",
    sorted(holding) == sorted(f["id"] for f in res["files"]),
    f"search {sorted(f['id'] for f in res['files'])}, fresh capinfos {sorted(holding)}",
)

independent = []
for fid in holding:
    out = tshark_container(
        [
            "tshark",
            "-o",
            "frame.generate_md5_hash:TRUE",
            "-r",
            f"/pcap/{fid}",
            "-Y",
            f"frame.time_epoch >= {start} && frame.time_epoch < {end} && ({filt})",
            "-T",
            "fields",
            "-e",
            "frame.time_epoch",
            "-e",
            "frame.len",
            "-e",
            "frame.md5_hash",
        ]
    )
    independent += [
        tuple(line.split("\t")) for line in out.splitlines() if line.count("\t") == 2
    ]
mine = [(r["t"], str(r["len"]), r["md5"]) for r in res["rows"]]
if res["termination"] == "eof":
    ok = sorted(mine) == sorted(independent)
    detail = f"{len(mine)} rows, independent {len(independent)}"
else:
    ok = set(mine) <= set(independent)
    detail = f"{len(mine)} rows all among the independent {len(independent)} ({res['termination']})"
check("rows equal an independent read", ok and len(mine) > 0, detail)
check(
    "rows in time order",
    all(dec(a[0]) <= dec(b[0]) for a, b in itertools.pairwise(mine)),
    "non-decreasing",
)

# 4 -----------------------------------------------------------------------------
step("Check 4: the download, read back by TShark")
code, blob = api(
    "POST", "/api/packets/download", {"manifest": res["manifest"]}, raw=True
)
back = []
if code == 200:
    out = tshark_container(
        [
            "tshark",
            "-o",
            "frame.generate_md5_hash:TRUE",
            "-r",
            "-",
            "-T",
            "fields",
            "-e",
            "frame.time_epoch",
            "-e",
            "frame.len",
            "-e",
            "frame.md5_hash",
        ],
        stdin=blob,
    )
    back = [
        tuple(line.split("\t")) for line in out.splitlines() if line.count("\t") == 2
    ]
check(
    "download equals the rows",
    code == 200 and back == mine,
    f"HTTP {code}, {len(blob) if code == 200 else 0} bytes, {len(back)} packets"
    + (" (over 512, so sparse selection is covered)" if len(back) > 512 else ""),
)

# 5 -----------------------------------------------------------------------------
step("Check 5: one packet's detail")
row = res["rows"][len(res["rows"]) // 2]
code, det = api(
    "POST", "/api/packets/packet", {"manifest": res["manifest"], "frame": row["n"]}
)
check(
    "detail matches its row",
    code == 200 and det.get("t") == row["t"] and det.get("md5") == row["md5"],
    f"HTTP {code}, frame {row['n']}, marking {det.get('marking')}, {len(det.get('layers', []))} layers",
)

# 6 -----------------------------------------------------------------------------
step("Check 6: field suggestions and the filter check")
code, fl = api("GET", "/api/packets/fields?prefix=tls.handshake.ext")
check(
    "field suggestions",
    code == 200 and len(fl.get("fields", [])) > 0,
    f"HTTP {code}, {len(fl.get('fields', []))} fields",
)
code, bad = api("POST", "/api/packets/check-filter", {"filter": "tcp.port =="})
check(
    "refuses a broken filter",
    code == 400 and "tshark" in bad.get("error", ""),
    f"HTTP {code}: {bad.get('error')}",
)
code, good = api(
    "POST",
    "/api/packets/check-filter",
    {"filter": 'tls.handshake.extensions_server_name contains "goog"'},
)
check("accepts a quoted filter", code == 200, f"HTTP {code}")
code, hostile = api(
    "POST",
    "/api/packets/search",
    {"filter": 'x"; rm -rf / #', "from": start, "to": end, "limit": 100},
)
check(
    "hostile filter is just a bad filter",
    code == 400,
    f"HTTP {code}: {hostile.get('error')}",
)

# 7 -----------------------------------------------------------------------------
step("Check 7: the last 60 s is provisional")
now = int(time.time())
code, live = api(
    "POST",
    "/api/packets/search",
    {"filter": "", "from": str(now - 60), "to": str(now), "limit": 100},
)
check(
    "recent window is provisional",
    code == 200 and live.get("provisional") is True,
    f"HTTP {code}, provisional {live.get('provisional')}, {len(live.get('rows', []))} rows, {live.get('termination')}",
)

# 8 -----------------------------------------------------------------------------
step("Check 8: nothing left running in nettap-tshark")
time.sleep(3)
procs = tshark_container(
    [
        "sh",
        "-c",
        "for p in /proc/[0-9]*; do tr '\\0' ' ' < $p/cmdline 2>/dev/null; echo; done",
    ]
)
left = [
    p
    for p in procs.splitlines()
    if re.search(r"\b(tshark|mergecap|editcap|capinfos|sleep)\b", p)
]
check("no leftover jobs", not left, f"{left[:5] or 'none'}")

print()
sys.exit(1 if FAILED else 0)
