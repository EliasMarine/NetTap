"""Read-only NET-219 check: QUIC is labelled once, "Unidentified" is split honestly, no ICS labels.

Runs inside nettap-storage-daemon (deploy-protocol-identification.sh passes it with `python3 -c`)
over one fixed window: from = the zeek-live recreate time (argv[1]), to = now at the start.
Zeek logs a connection when it ends, stamped with its start, so the window still grows: each
API figure is read between two direct counts (before <= API <= after); exact equality is used
only inside one API reply. Every query uses the API's filters (time range, Zeek conn records,
the daemon's live excluded-IP list). Nothing is written. Exit 0 when no check FAILs.
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from collections import Counter
from datetime import UTC, datetime

# The services the API replaces with exact filter counts; the rest come from its terms buckets
EXACT = ("quic", "ssl", "unknown")
COUNTERS = ("zeek.conn.orig_bytes", "zeek.conn.resp_bytes")
QUIC = {"term": {"network.protocol": "quic"}}
# Labels from Malcolm's ICS parsers, which ZEEK_DISABLE_ICS_ALL turns off (local.zeek, Malcolm's
# ICS protocol list). shortcut: prefixes typed from Malcolm's docs, not read from the image; add
# one if a new parser lands
ICS_PREFIXES = (
    "bacnet", "bsap", "c1222", "cip", "cotp", "dnp3", "ecat", "enip", "ethercat",
    "ge_srtp", "genisys", "hart_ip", "iec104", "iec60870", "modbus", "omron_fins",
    "opcua", "profinet", "roc_plus", "s7comm", "synchrophasor",
)  # fmt: skip
# One connection, as both its conn and its ssl record name it
TUPLE = ("source.ip", "source.port", "destination.ip")
# shortcut: one page of hits (10 minutes of QUIC is a few hundred); page if the window grows
PAGE = 10_000


# --- Pure checks (tested in daemon/tests/test_verify_protocols.py) ---


def bounded(before: int, value, after: int) -> bool:
    """A growing window: the direct count before the API call <= API <= the count after it."""
    return isinstance(value, int) and before <= value <= after


def terms_complete(agg: dict) -> bool:
    """A terms aggregation that left nothing out and counted every bucket exactly."""
    return (
        agg.get("sum_other_doc_count") == 0
        and agg.get("doc_count_error_upper_bound") == 0
    )


def partition_ok(split: dict, unknown: int) -> bool:
    """Inside one reply: conversations + one way + ICMP is the whole unknown entry."""
    parts = [split.get(k) for k in ("conversations", "one_way", "icmp")]
    return all(isinstance(p, int) for p in parts) and sum(parts) == unknown


def other_buckets(services: dict, before: dict, after: dict) -> tuple[str, str]:
    """The service entries the API takes from its terms buckets, against a direct terms read."""
    if not (terms_complete(before) and terms_complete(after)):
        return "INCONCLUSIVE", (
            "the direct terms aggregation left buckets out or estimated them "
            f"(sum_other_doc_count {before.get('sum_other_doc_count')}/{after.get('sum_other_doc_count')}, "
            f"doc_count_error_upper_bound {before.get('doc_count_error_upper_bound')}/"
            f"{after.get('doc_count_error_upper_bound')}); not compared"
        )
    b, a = _buckets(before), _buckets(after)
    names = sorted((set(services) | set(b) | set(a)) - set(EXACT))
    off = [
        f"{n} {b.get(n, 0):,} <= {services.get(n, 0):,} <= {a.get(n, 0):,}"
        for n in names
        if not bounded(b.get(n, 0), services.get(n, 0), a.get(n, 0))
    ]
    return (
        ("FAIL", "; ".join(off))
        if off
        else ("PASS", f"{len(names)} labels within bounds")
    )


def sni_on_quic(quic_hits: list, ssl_hits: list) -> list:
    """network.transport of each ssl record (with a server name) that belongs to a QUIC connection.

    Joined on the connection's addresses and source port, not on the ssl record's transport,
    which Malcolm may not set to udp.
    """
    quic = {_key(h) for h in quic_hits}
    return [_field(h, "network.transport") for h in ssl_hits if _key(h) in quic]


def evaluate(before: dict, reply: dict, after: dict, sni: list) -> list:
    """Every check as (verdict, label, detail); verdict is PASS, FAIL, INCONCLUSIVE or INFO."""
    services = {s["name"]: s["count"] for s in reply.get("services", [])}
    split = reply.get("unidentified") or {}
    total = after["total"]
    missing = total - after["counters"]
    out = [
        _check(
            total > 0,
            "conn records in the window",
            f"{total:,} (0 means indexing hasn't caught up)",
        ),
        _check(
            after["quic"] > 0,
            "QUIC conn records indexed",
            f"{after['quic']:,} (want more than 0)",
        ),
        _check(
            len(sni) > 0,
            "server names on QUIC connections",
            f"{len(sni):,} ssl records with zeek.ssl.server_name on a QUIC connection to udp/443 "
            f"(their network.transport: {dict(Counter(sni))})",
        ),
        _check(
            missing * 2 <= total,
            "conn records without byte counters",
            f"{missing:,} of {total:,} ({missing / total if total else 0:.1%}); most should have both",
        ),
    ]
    for label, value, key in (
        ("services quic", services.get("quic", 0), "quic"),
        ("services ssl (not QUIC)", services.get("ssl", 0), "ssl"),
        ("services unknown", services.get("unknown", 0), "unknown"),
        ("unidentified.icmp", split.get("icmp"), "icmp"),
        ("unidentified.one_way", split.get("one_way"), "one_way"),
    ):
        out.append(
            _check(
                bounded(before[key], value, after[key]),
                f"API {label}",
                f"direct {before[key]:,} <= API {value if value is not None else 'missing'} <= direct {after[key]:,}",
            )
        )
    parts = " + ".join(
        str(split.get(k, "missing")) for k in ("conversations", "one_way", "icmp")
    )
    out.append(
        _check(
            partition_ok(split, services.get("unknown", 0)),
            "conversations + one way + ICMP = unknown (one reply)",
            f"{parts} vs {services.get('unknown', 0):,}",
        )
    )
    verdict, detail = other_buckets(services, before["terms"], after["terms"])
    out.append((verdict, "other service labels", detail))
    out.append(
        _check(
            after["ics"] == 0,
            "ICS-labelled conn records",
            f"{after['ics']:,} {after['ics_names']} (want 0)",
        )
    )
    out.append(("INFO", "ayiya on udp/443", f"{after['ayiya']:,}"))
    return out


def _check(ok: bool, label: str, detail: str) -> tuple:
    return ("PASS" if ok else "FAIL", label, detail)


def _buckets(agg: dict) -> dict:
    return {b["key"]: b["doc_count"] for b in agg.get("buckets", [])}


def _field(hit: dict, name: str):
    values = hit.get("fields", {}).get(name) or [None]
    return values[0]


def _key(hit: dict) -> tuple:
    return tuple(_field(hit, f) for f in TUPLE)


def parse_reference(reply: dict) -> dict:
    a = reply["aggregations"]
    return {
        "total": reply["hits"]["total"]["value"],
        "quic": a["quic"]["doc_count"],
        "ssl": a["ssl"]["doc_count"],
        "unknown": a["unknown"]["doc_count"],
        "icmp": a["unknown"]["icmp"]["doc_count"],
        "one_way": a["unknown"]["one_way"]["doc_count"],
        "counters": a["counters"]["doc_count"],
        "ics": a["ics"]["doc_count"],
        "ics_names": _buckets(a["ics"]["names"]),
        "ayiya": a["ayiya"]["doc_count"],
        "terms": a["terms"],
    }


# --- I/O on the box ---


def api(path: str) -> dict:
    with open("/run/nettap-auth/daemon-token") as fh:
        token = fh.read().strip()
    req = urllib.request.Request(
        "http://localhost:8880" + path, headers={"X-NetTap-Daemon-Token": token}
    )
    return json.load(urllib.request.urlopen(req, timeout=300))


def reference(client, index: str, base: dict, icmp_transports: list) -> dict:
    """Every count the checks need, from one search (one point in time)."""
    icmp = {"terms": {"network.transport": icmp_transports}}
    both = [{"exists": {"field": f}} for f in COUNTERS]
    # conversations = payload both ways; one way = every other unlabelled non-ICMP record
    # (OLD CODE: both counters present and one <= 0, which left missing counters in conversations)
    two_way = {"bool": {"filter": [{"range": {f: {"gt": 0}}} for f in COUNTERS]}}
    one_way = {"bool": {"must_not": [icmp, two_way]}}
    unlabelled = {"bool": {"must_not": [{"exists": {"field": "network.protocol"}}]}}
    ics = {
        "bool": {
            "should": [{"prefix": {"network.protocol": p}} for p in ICS_PREFIXES],
            "minimum_should_match": 1,
        }
    }
    ayiya = [
        {"term": {"network.protocol": "ayiya"}},
        {"term": {"network.transport": "udp"}},
        {"term": {"destination.port": 443}},
    ]
    body = {
        "size": 0,
        "track_total_hits": True,
        "query": {"bool": base},
        "aggs": {
            "quic": {"filter": QUIC},
            "ssl": {
                "filter": {
                    "bool": {
                        "filter": [{"term": {"network.protocol": "ssl"}}],
                        "must_not": [QUIC],
                    }
                }
            },
            "unknown": {
                "filter": unlabelled,
                "aggs": {"icmp": {"filter": icmp}, "one_way": {"filter": one_way}},
            },
            "counters": {"filter": {"bool": {"filter": both}}},
            "ics": {
                "filter": ics,
                "aggs": {"names": {"terms": {"field": "network.protocol", "size": 50}}},
            },
            "ayiya": {"filter": {"bool": {"filter": ayiya}}},
            # the API's own terms aggregation, read directly
            "terms": {
                "terms": {"field": "network.protocol", "size": 50, "missing": "unknown"}
            },
        },
    }
    return parse_reference(client.search(index=index, body=body))


def quic_sni(client, index: str, t: dict, conn: list, excluded: list) -> list:
    """sni_on_quic over the window's QUIC conn records and its ssl records with a server name."""
    quic = client.search(
        index=index,
        body={
            "size": PAGE,
            "_source": False,
            "fields": list(TUPLE),
            "query": {"bool": {"filter": [t, *conn, QUIC], "must_not": excluded}},
        },
    )["hits"]["hits"]
    ports = sorted(
        {p for p in (_field(h, "source.port") for h in quic) if p is not None}
    )
    if not ports:
        return []
    ssl = client.search(
        index=index,
        body={
            "size": PAGE,
            "_source": False,
            "fields": [*TUPLE, "network.transport"],
            "query": {
                "bool": {
                    "filter": [
                        t,
                        {"term": {"event.provider": "zeek"}},
                        {"term": {"event.dataset": "ssl"}},
                        {"term": {"destination.port": 443}},
                        {"exists": {"field": "zeek.ssl.server_name"}},
                        {"terms": {"source.port": ports}},
                    ],
                    "must_not": excluded,
                }
            },
        },
    )["hits"]["hits"]
    return sni_on_quic(quic, ssl)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: verify_protocols.py <window start, ISO 8601 UTC>")
        return 2
    from_ts = sys.argv[1]
    datetime.fromisoformat(from_ts)  # fail early on a bad argument (3.11+ reads "Z")
    to_ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    sys.path.insert(0, "/opt/nettap/daemon")
    from api.traffic import _ZEEK_CONN_FILTERS, NETWORK_INDEX, _time_range_filter
    from main import _parse_curlrc_credentials
    from opensearchpy import OpenSearch  # only inside the daemon container
    from services.excluded_ips import build_excluded_ips_filter
    from services.iot_monitor import ICMP_TRANSPORTS

    client = OpenSearch(
        os.environ["OPENSEARCH_URL"],
        verify_certs=False,
        ssl_show_warn=False,
        timeout=120,
        http_auth=_parse_curlrc_credentials(os.environ["OPENSEARCH_CREDS_CONFIG_FILE"]),
    )
    t = _time_range_filter(from_ts, to_ts)
    # the daemon's runtime list: the owner's file plus the appliance's own address
    excluded = build_excluded_ips_filter(
        api("/api/settings/excluded-ips")["excluded_ips"]
    )
    base = {"filter": [t, *_ZEEK_CONN_FILTERS], "must_not": excluded}
    print(f"window {from_ts} -> {to_ts}")

    before = reference(client, NETWORK_INDEX, base, ICMP_TRANSPORTS)
    reply = api(
        "/api/traffic/protocols?"
        + urllib.parse.urlencode({"from": from_ts, "to": to_ts})
    )
    after = reference(client, NETWORK_INDEX, base, ICMP_TRANSPORTS)
    sni = quic_sni(client, NETWORK_INDEX, t, _ZEEK_CONN_FILTERS, excluded)

    results = evaluate(before, reply, after, sni)
    for verdict, label, detail in results:
        print(f"{verdict} {label}: {detail}")
    failed = sum(1 for r in results if r[0] == "FAIL")
    print(f"RESULT {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
