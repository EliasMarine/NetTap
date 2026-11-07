"""Check that the device's TShark compiles every ready-made filter on the Packet analysis page.

Runs INSIDE the daemon container. deploy-packet-analysis.sh passes the page's library as the
first argument:
    sudo docker exec -i nettap-storage-daemon python3 - "$(cat web/src/lib/utils/packet-library.json)" \
        < scripts/remote/verify-packet-library.py

Every group filter and every "What" kind filter goes to the daemon's real filter check, which
asks the TShark in nettap-tshark to compile it. A filter the device refuses would fail on the
page, so each one is a ✗ with TShark's own message. Read-only. Exits 1 on any failure.
"""

import json
import sys
import urllib.error
import urllib.request

FAILED = False


def check(label: str, ok: bool, detail: str) -> None:
    global FAILED
    print(f"   {'✓' if ok else '✗'} {label}: {detail}", flush=True)
    FAILED = FAILED or not ok


def compiles(filt: str) -> tuple[bool, str]:
    with open("/run/nettap-auth/daemon-token") as fh:
        token = fh.read().strip()
    req = urllib.request.Request(
        "http://localhost:8880/api/packets/check-filter",
        data=json.dumps({"filter": filt}).encode(),
        headers={"X-NetTap-Daemon-Token": token, "Content-Type": "application/json"},
        method="POST",
    )
    del token
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status == 200, f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        try:
            reason = json.loads(e.read()).get("error", "")
        except ValueError:
            reason = ""
        return False, f"HTTP {e.code}: {reason}"


def main() -> int:
    try:
        library = json.loads(sys.argv[1])
        groups, kinds = library["groups"], library["kinds"]
    except (IndexError, ValueError, KeyError, TypeError) as e:
        check("library read", False, f"no usable library JSON ({e})")
        return 1
    filters = [
        (g["label"], f["label"], f["filter"]) for g in groups for f in g["filters"]
    ]
    check(
        "library size",
        len(groups) == 6 and len(filters) == 37,
        f"{len(filters)} filters in {len(groups)} groups (the page shows 37 in 6)",
    )
    refused = 0
    for group, label, filt in filters + [
        ("What", k["label"], k["filter"]) for k in kinds
    ]:
        ok, detail = compiles(filt)
        refused += not ok
        if not ok:  # list only failures; the summary line counts the rest
            check(f"{group} › {label}", False, f"{filt!r} {detail}")
    total = len(filters) + len(kinds)
    check(
        "device TShark compiles them",
        refused == 0,
        f"{total - refused} of {total} accepted",
    )
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
