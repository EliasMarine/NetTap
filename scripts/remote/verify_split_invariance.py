"""Check that no page's figures depend on how OpenSearch splits the data (#93).

A window that spans several daily indices is counted per index and then merged; a terms
top-N then loses counts for terms outside one index's list. Today's data may sit in one index,
so this splits it artificially: OpenSearch's concurrent segment search in mode "all" cuts every
shard into slices that are counted and merged the same way. Each data endpoint is read with
the normal setting (A), with forced slicing (B), and normal again (A2); with A == A2, B must
equal A. The slicing setting is transient and always put back. No data is written.

Runs inside nettap-storage-daemon (verify-split-invariance.sh passes it with `python3 -c`).
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta

MODE = "search.concurrent_segment_search.mode"
# A float sum merged in another order may differ in its last bits
REL_TOL = 1e-9
# The time of the request, not a figure (LAN anomaly checks stamp it; no page shows it)
VOLATILE_KEYS = frozenset({"detected_at", "generated_at"})
TRAFFIC_CATEGORIES = [
    "streaming", "gaming", "social", "communication", "work", "iot", "cloud", "file_transfer", "dns",
    "email", "web", "security", "shopping", "news", "ads", "updates", "suspicious", "other",
]
ENDPOINTS = [
    "/api/alerts/categories", "/api/alerts/count", "/api/alerts/smart/summary", "/api/alerts/timeline",
    "/api/alerts/top-ips", "/api/alerts/top-signatures", "/api/alerts/smart",
    "/api/bandwidth/devices", "/api/bandwidth/heatmap",
    "/api/certificates", "/api/certificates/stats", "/api/certificates/self-signed", "/api/certificates/issuer-changes",
    "/api/devices?limit=500", "/api/devices/count",
    "/api/dns/nxdomain", "/api/dns/stats", "/api/dns/suspicious", "/api/dns/timeline", "/api/dns/top-domains", "/api/dns/types",
    "/api/iot/devices", "/api/iot/fleet-summary", "/api/iot/network-isolation", "/api/iot/privacy-report",
    "/api/iot/protocol-audit", "/api/iot/manufacturer-profiles", "/api/iot/anomalies",
    "/api/lan/anomalies", "/api/lan/arp-spoofing", "/api/lan/rogue-dhcp",
    "/api/logs/protocol-breakdown", "/api/logs/stats", "/api/logs/timeline", "/api/logs/top-destinations",
    "/api/logs/top-dns", "/api/logs/top-talkers",
    "/api/mac/randomized", "/api/mac/merge-suggestions",
    "/api/risk/scores",
    "/api/threats/beaconing", "/api/threats/dns-anomalies", "/api/threats/intel", "/api/threats/lateral",
    "/api/threats/report",
    "/api/traffic/bandwidth", "/api/traffic/categories", "/api/traffic/connections/sankey",
    "/api/traffic/connections/stats", "/api/traffic/connections/timeline", "/api/traffic/protocols",
    "/api/traffic/summary", "/api/traffic/top-destinations", "/api/traffic/top-talkers",
]


def first_difference(a, b, path: str = "") -> str | None:
    """Where two replies differ (None if equal; floats within REL_TOL)."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted((set(a) | set(b)) - VOLATILE_KEYS, key=str):
            if k not in a or k not in b:
                return f"{path}.{k} only in one"
            d = first_difference(a[k], b[k], f"{path}.{k}")
            if d:
                return d
        return None
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return f"{path} has {len(a)} vs {len(b)} items"
        for i, (x, y) in enumerate(zip(a, b, strict=True)):
            d = first_difference(x, y, f"{path}[{i}]")
            if d:
                return d
        return None
    numbers = isinstance(a, (int, float)) and isinstance(b, (int, float)) and (isinstance(a, float) or isinstance(b, float))
    if numbers and abs(a - b) <= REL_TOL * max(abs(a), abs(b), 1):
        return None
    return None if a == b else f"{path}: {a!r} vs {b!r}"[:300]


def api(path: str) -> dict:
    with open("/run/nettap-auth/daemon-token") as fh:
        token = fh.read().strip()
    req = urllib.request.Request("http://localhost:8880" + path, headers={"X-NetTap-Daemon-Token": token})
    return json.load(urllib.request.urlopen(req, timeout=300))


def main() -> int:
    sys.path.insert(0, "/opt/nettap/daemon")
    from main import _parse_curlrc_credentials
    from opensearchpy import OpenSearch  # only inside the daemon container

    client = OpenSearch(os.environ["OPENSEARCH_URL"], verify_certs=False, ssl_show_warn=False, timeout=120,
                        http_auth=_parse_curlrc_credentials(os.environ["OPENSEARCH_CREDS_CONFIG_FILE"]))
    now = datetime.now(UTC)
    # Ends an hour ago, so few late Zeek records land while A, B and A2 are read
    to_ts = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    from_ts = (now - timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%SZ")
    window = urllib.parse.urlencode({"from": from_ts, "to": to_ts})
    devices = api(f"/api/devices?{window}&limit=500")["devices"]
    busiest = sorted(devices, key=lambda d: d["connection_count"], reverse=True)[:3]
    paths = [f"{e}{'&' if '?' in e else '?'}{window}" for e in ENDPOINTS]
    paths += [f"/api/traffic/categories/{c}?{window}" for c in TRAFFIC_CATEGORIES]
    iot = api(f"/api/iot/devices?{window}").get("devices") or []
    if iot and iot[0].get("mac"):
        paths.append(f"/api/iot/devices/{urllib.parse.quote(iot[0]['mac'])}/baseline?{window}")
    for d in busiest:
        paths += [f"/api/devices/{d['ip']}?{window}", f"/api/devices/{d['ip']}/ports?{window}",
                  f"/api/devices/{d['ip']}/categories?{window}", f"/api/risk/scores/{d['ip']}?{window}",
                  f"/api/dns/device/{d['ip']}?{window}"]
        if d.get("mac"):
            paths.append(f"/api/devices/registry/{urllib.parse.quote(d['mac'])}/traffic?{window}")

    def read(path: str):
        client.indices.clear_cache(index="arkime_sessions3-*", request=True)
        try:
            return api(path)
        except (OSError, ValueError) as exc:  # HTTP and JSON errors: reported, not compared
            return {"_error": str(exc)}

    print(f"window {from_ts} -> {to_ts}; {len(paths)} endpoint reads")
    split, moving, failed, same = [], [], [], 0
    try:
        for path in paths:
            for _attempt in range(3):
                a = read(path)
                client.cluster.put_settings(body={"transient": {MODE: "all"}})
                b = read(path)
                client.cluster.put_settings(body={"transient": {MODE: None}})
                a2 = read(path)
                if first_difference(a, a2) is None:
                    break
            if "_error" in a:
                failed.append(f"{path.split('?')[0]}: {a['_error'][:120]}")
            elif (d := first_difference(a, a2)) is not None:
                moving.append(f"{path.split('?')[0]} {d}")
            elif (d := first_difference(a, b)) is not None:
                split.append(f"{path.split('?')[0]} {d}")
            else:
                same += 1
    finally:
        client.cluster.put_settings(body={"transient": {MODE: None}})
    print(f"SAME {same}")
    for line in split:
        print(f"SPLIT {line}")
    for line in moving:
        print(f"MOVING {line} (changed between two normal reads, so not compared)")
    for line in failed:
        print(f"FAILED {line}")
    settings = client.cluster.get_settings(flat_settings=True)
    print(f"MODE transient={settings['transient'].get(MODE)} persistent={settings['persistent'].get(MODE)}")
    print(f"RESULT {len(split) + len(failed)}")
    return 1 if split or failed else 0


if __name__ == "__main__":
    sys.exit(main())
