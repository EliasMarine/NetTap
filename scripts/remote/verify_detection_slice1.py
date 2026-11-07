"""Detection accuracy slice 1 checks (NET-191), run inside nettap-storage-daemon.

deploy-detection-slice1.sh passes this file with `python3 -c "$(cat …)" <command> <args>`:

  sids <device-ip>                       proxyware SIDs that device raised in 14 days, for its suppress lines
  counts <from> <to> before              raw OpenSearch vs the (old) API alert count
  counts <from> <to> after <old-total>   counted + activity == the old total; each matches a raw query
  pages <from> <to>                      the pages that count alerts answer; activity groups are level 5
  live <device-ip> <since> <sid,…>       suppressed SIDs raised by that device since activation (want 0)

Raw queries are written out here, not taken from api.alerts, so they check its rule rather than repeat it.
Read-only. Exit 0 ok, 1 a check failed.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

from main import _parse_curlrc_credentials
from opensearchpy import OpenSearch

INDEX = os.environ.get("OPENSEARCH_NETWORK_INDEX", "arkime_sessions3-*")
ACTIVITY = ["Informational", "Unknown"]
ALERTS = [
    {"term": {"event.provider": "suricata"}},
    {"term": {"event.dataset": "alert"}},
]
ENGINE = {"prefix": {"rule.name": "SURICATA "}}
# The owner runs Mysterium/Traffmonetizer (and their Go client) on purpose (2026-11-06)
PROXYWARE = re.compile(r"Bandwidth Sharing Tool|Go[- ]HTTP[- ]Client User-Agent", re.I)
# Major: large DNS query, possible covert channel; must keep firing
NEVER_SUPPRESS = {"2013075"}
PROBLEMS: list[str] = []


def client() -> OpenSearch:
    return OpenSearch(
        os.environ.get("OPENSEARCH_URL", "http://localhost:9200"),
        verify_certs=False,
        ssl_show_warn=False,
        http_auth=_parse_curlrc_credentials(
            os.environ.get("OPENSEARCH_CREDS_CONFIG_FILE", "")
        ),
    )


def call(path: str, **params: str) -> tuple[int, dict]:
    with open("/run/nettap-auth/daemon-token") as fh:
        token = fh.read().strip()
    url = f"http://localhost:8880{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"X-NetTap-Daemon-Token": token})
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        return exc.code, {}


def check(label: str, ok: bool, detail: str) -> None:
    print(f"{'✓' if ok else '✗'} {label}: {detail}")
    if not ok:
        PROBLEMS.append(label)


def window(frm: str, to: str) -> dict:
    return {
        "range": {
            "@timestamp": {"gte": frm, "lte": to, "format": "strict_date_optional_time"}
        }
    }


def sids(device: str) -> None:
    body = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    *ALERTS,
                    window("now-14d", "now"),
                    {"term": {"source.ip": device}},
                ]
            }
        },
        "aggs": {
            "sid": {
                "terms": {"field": "rule.id", "size": 500},
                "aggs": {
                    "name": {"terms": {"field": "rule.name", "size": 1}},
                    "sev": {
                        "terms": {
                            "field": "suricata.alert.metadata.signature_severity",
                            "size": 1,
                        }
                    },
                },
            }
        },
    }
    for b in client().search(index=INDEX, body=body)["aggregations"]["sid"]["buckets"]:
        name = (b["name"]["buckets"] or [{"key": ""}])[0]["key"]
        sev = (b["sev"]["buckets"] or [{"key": ""}])[0]["key"]
        sid = str(b["key"])
        # Only rules ET itself rates as activity: a counted rule is never silenced this way
        if PROXYWARE.search(name) and sev in ACTIVITY and sid not in NEVER_SUPPRESS:
            print(f"{sid}\t{b['doc_count']}\t{sev}\t{name}")


def raw(frm: str, to: str) -> tuple[int, int]:
    body = {
        "size": 0,
        "track_total_hits": True,
        "query": {"bool": {"filter": [*ALERTS, window(frm, to)], "must_not": [ENGINE]}},
        "aggs": {
            "activity": {
                "filter": {
                    "terms": {"suricata.alert.metadata.signature_severity": ACTIVITY}
                }
            }
        },
    }
    res = client().search(index=INDEX, body=body)
    return res["hits"]["total"]["value"], res["aggregations"]["activity"]["doc_count"]


def counts(frm: str, to: str, phase: str, old_total: str = "") -> None:
    total, activity = raw(frm, to)
    code, api = call("/api/alerts/count", **{"from": frm, "to": to})
    shown = api.get("counts", {}).get("total")
    if phase == "before":
        check(
            "old API count = raw rule alerts",
            code == 200 and shown == total,
            f"API {shown}, raw {total}",
        )
        print(
            f"  ({activity} of them ET Informational/Unknown, {total - activity} counted)"
        )
        print(f"OLD_TOTAL={shown}")
        return
    code_a, api_a = call(
        "/api/alerts/count", **{"from": frm, "to": to, "activity": "true"}
    )
    shown_a = api_a.get("counts", {}).get("total")
    check(
        "counted = raw counted",
        code == 200 and shown == total - activity,
        f"API {shown}, raw {total - activity}",
    )
    check(
        "activity = raw activity",
        code_a == 200 and shown_a == activity,
        f"API {shown_a}, raw {activity}",
    )
    same = (
        isinstance(shown, int) and isinstance(shown_a, int) and shown + shown_a == total
    )
    check(
        "counted + activity = every rule alert",
        same,
        f"{shown} + {shown_a} vs raw {total}",
    )
    if old_total:
        print(
            f"  (before the deploy the API counted {old_total} in this window; now {shown})"
        )


def pages(frm: str, to: str) -> None:
    win = {"from": frm, "to": to}
    for path in [
        "/api/alerts",
        "/api/alerts/categories",
        "/api/alerts/top-signatures",
        "/api/alerts/smart/summary",
        "/api/risk/scores",
        "/api/devices/count",
        "/api/iot/fleet-summary",
    ]:
        code, _ = call(path, **win)
        check(f"{path} answers", code == 200, f"HTTP {code}")
    code, listed = call("/api/alerts", **win, activity="true")
    check(
        "Activity list answers",
        code == 200 and listed.get("total", 0) > 0,
        f"HTTP {code}, {listed.get('total')} alerts",
    )
    code, _ = call("/api/alerts", **win, activity="yes")
    check("activity=yes is refused", code == 400, f"HTTP {code}")
    code, smart = call("/api/alerts/smart", **win, include_info="true", limit="500")
    groups = smart.get("alerts", [])
    act = [g for g in groups if g.get("activity")]
    wrong = [g.get("signature") for g in act if g.get("severity") != 5]
    check(
        "smart activity groups are level 5",
        code == 200 and bool(act) and not wrong,
        f"HTTP {code}, {len(act)} of {len(groups)} groups are activity, {len(wrong)} not level 5",
    )


def live(device: str, since: str, sid_list: str) -> None:
    c = client()
    base = [*ALERTS, window(since, "now")]

    def n(*extra: dict) -> int:
        body = {
            "size": 0,
            "track_total_hits": True,
            "query": {"bool": {"filter": [*base, *extra]}},
        }
        return c.search(index=INDEX, body=body)["hits"]["total"]["value"]

    supp = n(
        {"term": {"source.ip": device}}, {"terms": {"rule.id": sid_list.split(",")}}
    )
    everyone = n()
    # 0 suppressed proves nothing if nothing at all has been indexed since
    check(
        f"suppressed SIDs from {device} since {since}",
        supp == 0 and everyone > 0,
        f"{supp} (all alerts since: {everyone}; {device}'s others: {n({'term': {'source.ip': device}}) - supp})",
    )


def main() -> int:
    cmd, args = sys.argv[1], sys.argv[2:]
    {"sids": sids, "counts": counts, "pages": pages, "live": live}[cmd](*args)
    return 1 if PROBLEMS else 0


if __name__ == "__main__":
    sys.exit(main())
