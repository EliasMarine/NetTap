"""
Check the owner's device names and pictures end to end on the device (NET-200).

Runs INSIDE the daemon container (deploy-device-names-pictures.sh pipes it in):
    sudo docker exec -i nettap-storage-daemon python3 - < scripts/remote/verify-device-names.py

It picks one registry device the owner hasn't customised, then sets and clears a name, an icon
and a photo through the daemon API, checks each reply, the photo's headers and its version
rule, the refusals (SVG, unknown device), and that a backup carries both sections. Every
change is undone in a finally block, so the device ends as it started. Never prints the token.
"""

import base64
import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8880"
TOKEN = open("/run/nettap-auth/daemon-token").read().strip()
# A real 1×1 PNG
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
FAILED = False


def call(method: str, path: str, body: dict | None = None) -> tuple[int, dict, bytes]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("X-NetTap-Daemon-Token", TOKEN)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def check(label: str, ok: bool, detail: str = "") -> None:
    global FAILED
    print(f"   {'✓' if ok else '✗'} {label}{f' ({detail})' if detail else ''}")
    FAILED = FAILED or not ok


def device_of(raw: bytes) -> dict:
    try:
        return json.loads(raw).get("device") or {}
    except ValueError:
        return {}


status, _, raw = call("GET", "/api/devices/registry?limit=200")
devices = json.loads(raw).get("devices", []) if status == 200 else []
check("registry list answers", status == 200, f"HTTP {status}, {len(devices)} devices")
plain = [d for d in devices if not d.get("custom_name") and not d.get("icon") and not d.get("picture")]
if not plain:
    print("   ✗ no uncustomised device to test with")
    sys.exit(1)
target = plain[0]
mac = target["mac"]
base = f"/api/devices/registry/{mac}"
print(f"   Testing with {mac} (shown as {target.get('display_name')!r})")

try:
    status, _, raw = call("PUT", f"{base}/name", {"name": "  NetTap check  "})
    dev = device_of(raw)
    check("rename answers with the device", status == 200 and dev.get("display_name") == "NetTap check", f"HTTP {status}")
    check("the discovered name stays visible", dev.get("discovered_name") == target.get("display_name"))
    status, _, raw = call("GET", base)
    check("the detail shows the new name", device_of(raw).get("display_name") == "NetTap check")
    status, _, raw = call("DELETE", f"{base}/name")
    check("clearing brings the discovered name back", device_of(raw).get("display_name") == target.get("display_name"))

    status, _, raw = call("PUT", f"{base}/picture", {"icon": "tv"})
    check("an icon can be picked", status == 200 and device_of(raw).get("icon") == "tv", f"HTTP {status}")

    photo = "data:image/png;base64," + base64.b64encode(PNG).decode()
    status, _, raw = call("PUT", f"{base}/picture", {"image": photo})
    url = device_of(raw).get("picture") or ""
    check("a photo replaces the icon", status == 200 and url.startswith(f"{base}/picture?v=") and not device_of(raw).get("icon"), f"HTTP {status}")
    status, headers, body = call("GET", url)
    lower = {k.lower(): v for k, v in headers.items()}
    check("the photo serves its own bytes", status == 200 and body == PNG, f"HTTP {status}")
    check("served as a PNG image with nosniff", lower.get("content-type") == "image/png" and lower.get("x-content-type-options") == "nosniff")
    status, headers, _ = call("GET", f"{base}/picture?v=0000000000000000")
    lower = {k.lower(): v for k, v in headers.items()}
    check("a stale version is a 404 nobody caches", status == 404 and lower.get("cache-control") == "no-store", f"HTTP {status}")

    svg = "data:image/svg+xml;base64," + base64.b64encode(b"<svg/>").decode()
    status, _, raw = call("PUT", f"{base}/picture", {"image": svg})
    check("an SVG is refused", status == 400, json.loads(raw).get("error", "") if raw else "")
    status, _, _ = call("PUT", "/api/devices/registry/02:00:5E:00:00:00/name", {"name": "x"})
    check("an unknown device is a 404", status == 404, f"HTTP {status}")

    status, _, raw = call("GET", "/api/backup/export")
    sections = json.loads(raw).get("sections", {}) if status == 200 else {}
    check("a backup carries the names and pictures", status == 200 and "device_aliases" in sections and mac in sections.get("device_pictures", {}), f"HTTP {status}")
finally:
    call("DELETE", f"{base}/name")
    call("DELETE", f"{base}/picture")
    status, _, raw = call("GET", base)
    dev = device_of(raw)
    check("the test device is back as it was", not dev.get("custom_name") and not dev.get("picture") and not dev.get("icon"))

sys.exit(1 if FAILED else 0)
