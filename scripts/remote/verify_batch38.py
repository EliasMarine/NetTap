"""Batch 38 checks on real data: LAN detections, honest failures from the daemon system sweep.

Runs inside nettap-storage-daemon (deploy-data-accuracy-batch38.sh passes it with `python3 -c`).
Read-only: nothing is written; the two bad-filter calls only ask tshark to parse a filter.
"""

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

PROBLEMS: list[str] = []
BAD_FILTER = "dns &&& nettap_not_a_field"


def call(path: str, body: dict | None = None, **params) -> tuple[int, dict]:
    with open("/run/nettap-auth/daemon-token") as fh:
        token = fh.read().strip()
    query = ("?" + urllib.parse.urlencode(params)) if params else ""
    req = urllib.request.Request(
        "http://localhost:8880" + path + query,
        headers={"X-NetTap-Daemon-Token": token, "Content-Type": "application/json"},
        data=None if body is None else json.dumps(body).encode(),
        method="GET" if body is None else "POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.load(exc)
        except ValueError:
            return exc.code, {}


def check(label: str, ok: bool, detail: str) -> None:
    print(f"{'✓' if ok else '✗'} {label}: {detail}")
    if not ok:
        PROBLEMS.append(label)


def lan(window: dict) -> None:
    status, dhcp = call("/api/lan/rogue-dhcp", **window)
    # this network has one DHCP server (the gateway, one address per VLAN): batch 37 showed 4 "rogue" clients
    check("rogue DHCP: no device renewing a lease is called a server", status == 200 and dhcp.get("count") == 0,
          f"HTTP {status}, {dhcp.get('count')} alerts {[a.get('server_ip') for a in dhcp.get('alerts', [])][:4]}")
    status, allx = call("/api/lan/anomalies", **window)
    check("ARP checks say they had no ARP to look at", status == 200 and allx.get("arp_recorded") is False and bool(allx.get("note")),
          f"HTTP {status}, arp_recorded={allx.get('arp_recorded')}, note={str(allx.get('note'))[:60]!r}")
    status, iot = call("/api/iot/anomalies", **window)
    check("IoT anomalies answer (every value compared with the baseline)", status == 200,
          f"HTTP {status}, {len(iot.get('anomalies', []))} anomalies")


def bad_filters() -> None:
    _, pcaps = call("/api/tshark/pcaps")
    files = sorted(pcaps.get("pcaps", []), key=lambda p: p["modified"], reverse=True)
    target = next((p for p in files[1:] if 1e6 < p["size_bytes"] < 400e6), None)
    if target is None:
        check("a PCAP file to test with", False, f"{len(files)} files, none between 1 and 400 MB")
        return
    status, r = call("/api/tshark/analyze", {"pcap_path": target["path"], "display_filter": BAD_FILTER, "max_packets": 5})
    check("TShark: a filter it refuses is an error, not 'no matches'", status == 400 and bool(r.get("error")),
          f"HTTP {status}, error {str(r.get('error'))[:90]!r}")
    _, listed = call("/api/pcap/files")
    full = next((f["file"] for f in listed.get("files", []) if f["file"].endswith("/" + target["name"])), None)
    status, p = call("/api/pcap/preview", file=full, filter=BAD_FILTER, limit=5)
    check("PCAP preview: a filter it refuses is an error, not 'no packets'", status == 400 and bool(p.get("error")),
          f"HTTP {status}, error {str(p.get('error'))[:90]!r}")


def system() -> None:
    _, net = call("/api/internet/health")
    st, loss = net.get("status"), net.get("packet_loss_pct")
    consistent = (st != "unknown" or (loss is None and bool(net.get("error")))) and (st != "down" or loss is not None)
    check("internet health: 'down' only from a ping that ran", consistent, f"status={st} loss={loss} error={net.get('error')!r}")
    _, br = call("/api/bridge/health")
    lat = br.get("latency_us")
    check("bridge latency is measured or says why not (no made-up 50 µs)", lat is None and bool(br.get("latency_note")) or isinstance(lat, (int, float)) and lat != 50,
          f"latency_us={lat} note={br.get('latency_note')!r}")
    _, storage = call("/api/storage/status")
    check("exact top-N counts are on", storage.get("exact_counts") is True, f"exact_counts={storage.get('exact_counts')}")
    _, upd = call("/api/system/updates/available")
    sizes = [u.get("size_mb") for u in upd.get("updates", [])]
    print(f"  (info) updates: {len(sizes)} available, sizes {sizes[:5]}, couldn't check: {upd.get('failed_checks') or 'none'}")
    _, vers = call("/api/system/versions")
    rules = [c for c in vers.get("components", []) if "rule" in str(c.get("name", "")).lower()]
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    print(f"  (info) rules versions {[(c.get('name'), c.get('current_version'), c.get('status')) for c in rules]} (today {today})")


def main() -> int:
    end = datetime.now(UTC).replace(second=0, microsecond=0)
    window = {"from": (end - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ"), "to": end.strftime("%Y-%m-%dT%H:%M:%SZ")}
    print(f"window {window['from']} -> {window['to']}")
    t0 = time.time()
    for step in (lambda: lan(window), bad_filters, system):
        try:
            step()
        except Exception as exc:  # noqa: BLE001 - report and go on: one failed check must not hide the others
            check("check ran", False, f"{type(exc).__name__}: {str(exc)[:300]}")
    print(f"RESULT {len(PROBLEMS)} ({round(time.time() - t0, 1)} s)")
    return 1 if PROBLEMS else 0


if __name__ == "__main__":
    sys.exit(main())
