"""NET-209 on the device: the threat and risk scores before and after, and their new rules.

Runs inside nettap-storage-daemon (deploy-threat-accuracy.sh pipes it to `python3 -`):
  snapshot        print the figures as JSON (run against the old daemon before the rebuild)
  check <before>  the same figures from the new daemon, the checks, and a before/after table

Reads only: the daemon API (with its token, never printed) and OpenSearch searches. No writes.
"""

import json
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta

sys.path.insert(0, "/opt/nettap/daemon")

DAEMON = "http://localhost:8880"
SCANNER = "91.92.40.12"  # the internet scanner that was shown as a device
FACTORS = ["alert_count", "connection_anomaly", "upload_spike"]
WINDOWS = {"24h": timedelta(hours=24), "7d": timedelta(days=7)}
NOW = datetime.now(UTC).replace(second=0, microsecond=0)


def iso(when: datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def api(path: str) -> tuple[int, dict]:
    with open("/run/nettap-auth/daemon-token") as f:
        token = f.read().strip()
    req = urllib.request.Request(DAEMON + path, headers={"X-NetTap-Daemon-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as err:
        return err.code, {}


def figures() -> dict:
    out: dict = {}
    for name, span in WINDOWS.items():
        q = f"?from={iso(NOW - span)}&to={iso(NOW)}"
        status, s = api("/api/alerts/smart/summary" + q)
        out[f"summary_{name}"] = {
            "status": status,
            **{k: s.get(k) for k in ("threat_score", "threat_level", "total_groups",
                                     "total_events", "informational_events")},
            "chains": [[c.get("source_ip"), c.get("stages")] for c in s.get("kill_chains") or []],
        }
    q = f"?from={iso(NOW - WINDOWS['24h'])}&to={iso(NOW)}"
    status, r = api("/api/risk/scores" + q)
    out["risk"] = {
        "status": status,
        "devices": [
            {"ip": d["ip"], "score": d["score"], "level": d["level"], "alerts": d.get("alert_count"),
             "factors": [[f["name"], f["score"]] for f in d.get("factors", [])]}
            for d in r.get("devices", [])
        ],
    }
    status, single = api(f"/api/risk/scores/{SCANNER}{q}")
    out["scanner_risk"] = {"status": status, "score": single.get("score"), "level": single.get("level")}
    out["scanner_device"] = {"status": api(f"/api/devices/{SCANNER}{q}")[0]}
    return out


def history_cross_check(ips: list[str]) -> list[str]:
    """Each day range's connections and internet bytes from _history vs an independent search."""
    import os

    from api.risk import NOT_INTERNET_CIDRS, _day_ranges, _history, _ms
    from main import _parse_curlrc_credentials, load_config
    from services.excluded_ips import detect_and_build_lan_filter
    from storage.manager import StorageManager

    cfg = load_config()
    auth = _parse_curlrc_credentials(os.environ.get("OPENSEARCH_CREDS_CONFIG_FILE", ""))
    client = StorageManager._create_client(cfg["opensearch_url"], auth)
    app = {"lan_filter": detect_and_build_lan_filter(client), "excluded_ips": []}
    index = os.environ.get("OPENSEARCH_NETWORK_INDEX", "arkime_sessions3-*")
    frm, to = iso(NOW - WINDOWS["24h"]), iso(NOW)
    every = _history(client, app, frm, to)
    problems = []

    def search(filters: list, must_not: list, field: str) -> tuple[int, int]:
        body = {"size": 0, "track_total_hits": True,
                "query": {"bool": {"filter": filters, "must_not": must_not}},
                "aggs": {"b": {"sum": {"field": field, "missing": 0}}}}
        r = client.search(index=index, body=body)
        return r["hits"]["total"]["value"], int(r["aggregations"]["b"]["value"] or 0)

    for ip in ips:
        one = _history(client, app, frm, to, ip)
        for i, rng in enumerate(_day_ranges(_ms(frm), _ms(to))):
            base = [{"range": {"@timestamp": {"gte": rng["from"], "lt": rng["to"], "format": "epoch_millis"}}},
                    {"term": {"event.provider": "zeek"}}, {"term": {"event.dataset": "conn"}}]
            conns, _ = search([*base, {"term": {"source.ip": ip}}], [], "source.bytes")
            _, sent = search([*base, {"term": {"source.ip": ip}}],
                             [{"terms": {"destination.ip": NOT_INTERNET_CIDRS}}], "source.bytes")
            _, answered = search([*base, {"term": {"destination.ip": ip}}],
                                 [{"terms": {"source.ip": NOT_INTERNET_CIDRS}}], "destination.bytes")
            want = {"connections": conns, "upload_bytes": sent + answered}
            for label, rows in (("list", every.get(ip)), ("single", one.get(ip))):
                got = rows[i] if rows else {"connections": 0, "upload_bytes": 0}
                if got != want:
                    problems.append(f"{ip} range {i} ({label}): {got} vs independent {want}")
    return problems


def check(before: dict) -> int:
    after = figures()
    failed = 0

    def ok(label: str, passed: bool, detail: str) -> None:
        nonlocal failed
        print(f"   {'✓' if passed else '✗'} {label}: {detail}")
        failed |= not passed

    ok(f"/api/devices/{SCANNER}", after["scanner_device"]["status"] == 404,
       f"HTTP {after['scanner_device']['status']} (was {before.get('scanner_device', {}).get('status')})")
    ok(f"/api/risk/scores/{SCANNER}", after["scanner_risk"]["status"] == 404,
       f"HTTP {after['scanner_risk']['status']} (was {before.get('scanner_risk')})")
    from services.alert_findings import lan_test

    is_lan = lan_test(None)
    for name in WINDOWS:
        s = after[f"summary_{name}"]
        outside = [c[0] for c in s["chains"] if not is_lan(c[0])]
        ok(f"{name} summary answers", s["status"] == 200, f"HTTP {s['status']}")
        ok(f"{name} kill chains are LAN devices", not outside, f"{len(s['chains'])} chain(s), outside: {outside}")
    risk = after["risk"]
    ok("risk list answers", risk["status"] == 200, f"HTTP {risk['status']}, {len(risk['devices'])} devices")
    wrong = [d["ip"] for d in risk["devices"] if [f[0] for f in d["factors"]] != FACTORS]
    ok("every device has the three factors", not wrong, f"wrong: {wrong[:5]}")

    busiest = [d["ip"] for d in risk["devices"]][:2]
    problems = history_cross_check(busiest) if busiest else ["no devices to check"]
    ok(f"history ranges match independent searches ({', '.join(busiest)})", not problems,
       "; ".join(problems[:4]) or "8 ranges × list and single")

    print("\n   Before → after")
    for name in WINDOWS:
        b, a = before.get(f"summary_{name}", {}), after[f"summary_{name}"]
        print(f"   {name}: score {b.get('threat_score')} {b.get('threat_level')} → "
              f"{a['threat_score']} {a['threat_level']}; counted alerts {b.get('total_events')} → "
              f"{a['total_events']}; not counted {b.get('informational_events')} → {a['informational_events']}")
        print(f"        kill chains {b.get('chains')} → {a['chains']}")
    old = {d["ip"]: d for d in before.get("risk", {}).get("devices", [])}
    print("   Risk (24 h), top 8 before and after:")
    for ip in list(dict.fromkeys([*list(old)[:8], *[d["ip"] for d in risk["devices"][:8]]])):
        new = next((d for d in risk["devices"] if d["ip"] == ip), None)
        was = old.get(ip)
        print(f"     {ip:<16} {was and was['score']} {was and was['level']} → "
              f"{new and new['score']} {new and new['level']}  {new and new['factors']}")
    return failed


if __name__ == "__main__":
    if sys.argv[1] == "snapshot":
        print(json.dumps(figures()))
    else:
        with open(sys.argv[2]) as f:
            sys.exit(check(json.load(f)))
