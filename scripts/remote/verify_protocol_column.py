"""#141 check, run inside nettap-storage-daemon: packet tables show Wireshark's own columns.

Before the fix, the TShark table and the PCAP preview took the protocol from the last entry
of frame.protocols, so 97 of 100 QUIC packets read "DATA" where Wireshark says UDP, and the
preview's addresses came from ip.src/ip.dst, blank for IPv6 and ARP. Reads one finished
capture file both ways. Read-only: GET requests and a TShark analysis (it only reads a file).
"""

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

PACKETS = 200
with open("/run/nettap-auth/daemon-token") as token_file:
    TOKEN = token_file.read().strip()


def call(path: str, params: dict | None = None, body: dict | None = None):
    url = "http://localhost:8880" + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    headers = {"X-NetTap-Daemon-Token": TOKEN, "Content-Type": "application/json"}
    try:
        request = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(request, timeout=120) as reply:
            return reply.status, json.loads(reply.read())
    except urllib.error.HTTPError as exc:
        return exc.code, {}
    except Exception as exc:  # noqa: BLE001 — any failure is reported, not hidden
        print(f"✗ request failed: {path}: {exc}")
        return 0, {}


def check(label: str, ok: bool, detail: str) -> bool:
    print(f"{'✓' if ok else '✗'} {label}: {detail}")
    return ok


def wireshark_name(protocol: str) -> bool:
    return bool(protocol) and ":" not in protocol and protocol.lower() != "data"


code, listing = call("/api/pcap/files")
files = sorted(listing.get("files") or [], key=lambda f: str(f.get("modified")))
if code != 200 or len(files) < 2:
    check("capture files", False, f"HTTP {code}, {len(files)} files")
    sys.exit(1)
path = files[-2]["file"]  # the newest one may still be being written
print(f"  file {path}")
all_ok = True

code, preview = call("/api/pcap/preview", {"file": path, "limit": PACKETS})
packets = preview.get("packets") or []
protocols = Counter(p.get("protocol", "") for p in packets)
odd = [p for p in protocols if not wireshark_name(p)]
blank = sum(1 for p in packets if not p.get("source") or not p.get("destination"))
all_ok &= check(
    "PCAP preview protocols",
    code == 200 and len(packets) > 0 and not odd,
    f"HTTP {code}, {len(packets)} packets, {dict(protocols.most_common(5))}, not Wireshark names: {odd}",
)
all_ok &= check(
    "PCAP preview addresses",
    len(packets) > 0 and blank == 0,
    f"{blank} packets without a source or destination",
)

# the TShark API takes its own container's path for the same file
code, pcaps = call("/api/tshark/pcaps")
name = files[-2].get("name") or path.rsplit("/", 1)[-1]
tshark_path = next(
    (p["path"] for p in pcaps.get("pcaps") or [] if p.get("name") == name), None
)
if not tshark_path:
    check("TShark file list", False, f"HTTP {code}, {name} not listed")
    sys.exit(1)
body = {"pcap_path": tshark_path, "max_packets": PACKETS, "output_format": "json"}
code, analysis = call("/api/tshark/analyze", body=body)
layers = [
    (p.get("_source") or {}).get("layers") or {} for p in analysis.get("packets") or []
]
protocols = Counter(lay.get("_ws.col.Protocol", "") for lay in layers)
odd = [p for p in protocols if not wireshark_name(p)]
all_ok &= check(
    "TShark table protocols",
    code == 200 and len(layers) > 0 and not odd,
    f"HTTP {code}, {len(layers)} packets, {dict(protocols.most_common(5))}, not Wireshark names: {odd}",
)
sys.exit(0 if all_ok else 1)
