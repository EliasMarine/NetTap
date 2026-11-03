"""Batch 47 checks: Devices names a device as Home does (#130).

192.168.1.188 (EliasMacStudio on Home) read "sarabouzeid-fgwk3p497k.local" on Devices: the name
came from mDNS the router reflects between VLANs, where Arkime keeps every host's names and IPs
in two unpaired lists. Devices and Device detail now use the registry's name for the MAC (the
one Home shows), and a DNS name only when DNS ties it to the IP.

Runs inside nettap-storage-daemon (deploy-data-accuracy-batch47.sh passes it with `python3 -c`).
Read-only.
"""

import json
import sys
import urllib.error
import urllib.request

PROBLEMS: list[str] = []
NOT_HOSTNAMES = ("._tcp.", "._udp.", ".in-addr.arpa", ".ip6.arpa", "_asquic")


def call(path: str) -> tuple[int, dict]:
    with open("/run/nettap-auth/daemon-token") as fh:
        token = fh.read().strip()
    req = urllib.request.Request("http://localhost:8880" + path, headers={"X-NetTap-Daemon-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        return exc.code, {}


def check(label: str, ok: bool, detail: str) -> None:
    print(f"{'✓' if ok else '✗'} {label}: {detail}")
    if not ok:
        PROBLEMS.append(label)


def home_names() -> dict[str, str]:
    """{MAC: the name Home shows} where that's a name, not the vendor or MAC fallback."""
    _, reg = call("/api/devices/registry?limit=1000")
    names = {}
    for d in reg.get("devices", []):
        name = d.get("display_name")
        if name and name not in (d.get("manufacturer"), d.get("mac")):
            names[d["mac"].upper()] = name
    return names


def main() -> int:
    names = home_names()
    code, listed = call("/api/devices?limit=500")
    devices = listed.get("devices", [])
    check("Devices list answers", code == 200 and bool(devices), f"HTTP {code}, {len(devices)} devices")
    named = [d for d in devices if (d.get("mac") or "").upper() in names]
    wrong = [f"{d['ip']}: {d.get('hostname')!r} vs Home {names[d['mac'].upper()]!r}"
             for d in named if d.get("hostname") != names[d["mac"].upper()]]
    check("Devices list names every device as Home does", bool(named) and not wrong,
          f"{len(named)} devices Home names, {len(wrong)} differ {wrong[:5] or ''}".strip())
    services = [f"{d['ip']}: {d['hostname']}" for d in devices
                if d.get("hostname") and (d["hostname"].startswith("_") or any(x in d["hostname"] for x in NOT_HOSTNAMES))]
    check("no Devices name is an mDNS service or reverse-lookup name", not services, f"{services[:5] or 'none'}")
    detail_wrong = []
    for d in named[:8]:
        _, one = call(f"/api/devices/{d['ip']}")
        got = one.get("device", {}).get("hostname")
        if got != names[d["mac"].upper()]:
            detail_wrong.append(f"{d['ip']}: {got!r}")
    check("Device detail names them as Home does too", bool(named) and not detail_wrong,
          f"{min(len(named), 8)} checked, differ {detail_wrong or 'none'}")
    studio = next((d for d in devices if d["ip"] == "192.168.1.188"), None)
    if studio:
        print(f"  (info) 192.168.1.188: Devices {studio.get('hostname')!r}, Home {names.get((studio.get('mac') or '').upper())!r}")
    print(f"\n{len(PROBLEMS)} problem(s)" + (f": {', '.join(PROBLEMS)}" if PROBLEMS else ""))
    return 1 if PROBLEMS else 0


sys.exit(main())
