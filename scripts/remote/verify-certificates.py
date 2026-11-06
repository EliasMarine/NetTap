"""
Check the Certificates page's figures against an independent recount (NET-154, PLAN.md §7).

Runs INSIDE the daemon container, read-only (deploy-certificates-findings.sh pipes it in):
    sudo docker exec -i nettap-storage-daemon python3 - < scripts/remote/verify-certificates.py
Arguments pick windows by hours (e.g. `python3 - 24`); none means 24, 168 and 720.

For each window (24 h, 7 d, 30 d) it opens one point-in-time snapshot and:
  1. runs the page's pass on it (CertificateMonitor.overview) and times it, sizes the reply and
     measures memory growth;
  2. recounts the same snapshot with its own code: chain[0] per session, per certificate, per
     site and per status, plus which certificates have stored x509 details;
  3. compares them, and reconciles the total with an exact count of the eligible ssl records.

Limits (a failure exits 1): each pass ≤ 45 s, reply ≤ 5 MB, memory growth ≤ 300 MB.
A 30-day pass within these limits is a release requirement.
"""

import os
import resource
import sys
import time
from datetime import UTC, datetime, timedelta

from main import _parse_curlrc_credentials
from opensearchpy import OpenSearch
from services.cert_monitor import CertificateMonitor
from services.cert_overview import (
    NETWORK_INDEX,
    Budget,
    CertQueryFailed,
    encode_bounded,
    paginate,
)
from services.excluded_ips import build_excluded_ips_filter, load_excluded_ips

WINDOWS = [("24 hours", 24), ("7 days", 168), ("30 days", 720)]
MAX_SECONDS, MAX_BYTES, MAX_RSS_MB = 45.0, 5_000_000, 300
CHAIN = "zeek.ssl.cert_chain_fps"
FAILED = False


def check(label: str, ok: bool, detail: str) -> None:
    global FAILED
    print(f"   {'✓' if ok else '✗'} {label}: {detail}")
    FAILED = FAILED or not ok


def rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # KB on Linux


def client() -> OpenSearch:
    creds = _parse_curlrc_credentials(
        os.environ.get("OPENSEARCH_CREDS_CONFIG_FILE", "")
    )
    return OpenSearch(
        os.environ.get("OPENSEARCH_URL", "http://localhost:9200"),
        http_auth=creds,
        verify_certs=False,
        ssl_show_warn=False,
        timeout=120,
        max_retries=0,
        retry_on_timeout=False,
    )


def eligible(from_ts: str, to_ts: str, excluded: list[str]) -> dict:
    """The ssl records the page counts, written out here rather than imported."""
    query: dict = {
        "bool": {
            "filter": [
                {
                    "range": {
                        "@timestamp": {
                            "gte": from_ts,
                            "lte": to_ts,
                            "format": "strict_date_optional_time",
                        }
                    }
                },
                {"term": {"event.provider": "zeek"}},
                {"term": {"event.dataset": "ssl"}},
                {"exists": {"field": CHAIN}},
            ]
        }
    }
    if excluded:
        query["bool"]["must_not"] = build_excluded_ips_filter(excluded)
    return query


def recount(os_client: OpenSearch, pit: str, query: dict) -> dict:
    """Sessions per certificate, site and status, by paging the snapshot with search_after."""
    per_cert: dict[str, int] = {}
    per_site: dict[str, int] = {}
    per_status: dict[str, int] = {}
    later_in_chain: set[str] = set()
    firsts: list[str] = []
    after = None
    while True:
        body: dict = {
            "size": 10_000,
            "query": query,
            "_source": [CHAIN],
            "docvalue_fields": [
                "zeek.ssl.server_name",
                "destination.ip",
                "zeek.ssl.validation_status",
            ],
            "sort": [{"_shard_doc": "asc"}],
            "pit": {"id": pit, "keep_alive": "5m"},
            "track_total_hits": False,
        }
        if after:
            body["search_after"] = after
        reply = os_client.search(body=body, request_timeout=120)
        if reply.get("timed_out") or (reply.get("_shards") or {}).get("failed"):
            raise RuntimeError("the recount's own page was incomplete")
        pit = reply.get("pit_id") or pit
        hits = reply["hits"]["hits"]
        for hit in hits:
            chain = ((hit.get("_source") or {}).get("zeek") or {}).get("ssl", {}).get(
                "cert_chain_fps"
            ) or []
            chain = [chain] if isinstance(chain, str) else [c for c in chain if c]
            if not chain:
                continue
            fields = hit.get("fields") or {}
            sni = (fields.get("zeek.ssl.server_name") or [None])[0]
            server = (fields.get("destination.ip") or [None])[0]
            status = (fields.get("zeek.ssl.validation_status") or [None])[
                0
            ] or "unchecked"
            site = sni or f"no-sni:{server or 'unknown'}"
            per_cert[chain[0]] = per_cert.get(chain[0], 0) + 1
            per_site[site] = per_site.get(site, 0) + 1
            per_status[status] = per_status.get(status, 0) + 1
            later_in_chain.update(chain[1:])
            firsts.append(chain[0])
        if len(hits) < 10_000:
            break
        after = hits[-1]["sort"]
    reordered = sum(1 for fp in firsts if fp in later_in_chain)
    return {
        "cert": per_cert,
        "site": per_site,
        "status": per_status,
        "reordered": reordered,
    }


def with_details(os_client: OpenSearch, pit: str, fingerprints: list[str]) -> set[str]:
    """Fingerprints that have at least one stored x509 record, at any time."""
    found: set[str] = set()
    for i in range(0, len(fingerprints), 1000):
        chunk = fingerprints[i : i + 1000]
        reply = os_client.search(
            body={
                "size": 0,
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"event.dataset": "x509"}},
                            {"terms": {"zeek.x509.fingerprint": chunk}},
                        ]
                    }
                },
                "aggs": {
                    "fps": {
                        "terms": {"field": "zeek.x509.fingerprint", "size": len(chunk)}
                    }
                },
                "pit": {"id": pit, "keep_alive": "5m"},
            },
            request_timeout=120,
        )
        found.update(str(b["key"]) for b in reply["aggregations"]["fps"]["buckets"])
    return found


def exact_total(os_client: OpenSearch, pit: str, query: dict) -> int:
    reply = os_client.search(
        body={
            "size": 0,
            "query": query,
            "track_total_hits": True,
            "pit": {"id": pit, "keep_alive": "5m"},
        },
        request_timeout=120,
    )
    return int(reply["hits"]["total"]["value"])


def diff(page: dict[str, int], raw: dict[str, int]) -> str:
    bad = [k for k in set(page) | set(raw) if page.get(k) != raw.get(k)]
    return "; ".join(
        f"{k[:40]} page {page.get(k)} raw {raw.get(k)}" for k in sorted(bad)[:5]
    )


def verify_window(
    os_client: OpenSearch, words: str, hours: int, excluded: list[str], base_rss: float
) -> None:
    to = datetime.now(UTC) - timedelta(
        minutes=15
    )  # a closed window: late records can't land mid-check
    from_ts, to_ts = (to - timedelta(hours=hours)).isoformat(), to.isoformat()
    print(f"→ Last {words} ({from_ts[:16]} to {to_ts[:16]} UTC)")
    pit = os_client.create_pit(
        index=NETWORK_INDEX, keep_alive="10m", allow_partial_pit_creation="false"
    )["pit_id"]
    try:
        start = time.monotonic()
        try:
            budget = Budget()
            data = CertificateMonitor(os_client).overview(
                from_ts, to_ts, excluded, budget=budget, pit_id=pit
            )
            size = len(encode_bounded(paginate(data, 5_000), budget))
        except CertQueryFailed as exc:
            check("the page's pass", False, f"{type(exc).__name__}: {exc}")
            return
        seconds = time.monotonic() - start
        grown = (
            rss_mb() - base_rss
        )  # peak memory above what the process used before any pass
        check(
            "time",
            seconds <= MAX_SECONDS,
            f"{seconds:.1f} s (limit {MAX_SECONDS:.0f} s)",
        )
        check("reply size", size <= MAX_BYTES, f"{size / 1e6:.2f} MB (limit 5 MB)")
        check(
            "memory growth",
            grown <= MAX_RSS_MB,
            f"{grown:.0f} MB (limit {MAX_RSS_MB} MB)",
        )

        query = eligible(from_ts, to_ts, excluded)
        raw = recount(os_client, pit, query)
        total = exact_total(os_client, pit, query)
        summary = data["summary"]
        page_cert = {c["fingerprint"]: c["sessions"] for c in data["certificates"]}
        page_site = {s["id"]: s["sessions"] for s in data["sites"]}
        page_status: dict[str, int] = {}
        for s in data["sites"]:
            for status, n in s["statuses"].items():
                page_status[status] = page_status.get(status, 0) + n
        check(
            "sessions per certificate",
            page_cert == raw["cert"],
            f"{len(page_cert)} certificates"
            + (
                f" — {diff(page_cert, raw['cert'])}" if page_cert != raw["cert"] else ""
            ),
        )
        check(
            "sessions per site",
            page_site == raw["site"],
            f"{len(page_site)} sites"
            + (
                f" — {diff(page_site, raw['site'])}" if page_site != raw["site"] else ""
            ),
        )
        check(
            "sessions per status",
            page_status == raw["status"],
            ", ".join(f"{k} {v}" for k, v in sorted(page_status.items())),
        )
        check(
            "total sessions",
            summary["sessions"] == total == sum(raw["cert"].values()),
            f"page {summary['sessions']}, recount {sum(raw['cert'].values())}, exact count {total}",
        )
        detailed = with_details(os_client, pit, sorted(raw["cert"]))
        missing = len(raw["cert"]) - len(detailed & set(raw["cert"]))
        check(
            "certificates without details",
            summary["certificates_without_details"] == missing,
            f"page {summary['certificates_without_details']}, recount {missing}",
        )
        print(
            f"   · findings: {summary['findings']}; your devices: {summary['local_certificates']} certificates on {summary['local_endpoints']} services"
        )
        print(
            f"   · data quality: {raw['reordered']} sessions' first certificate appears later in another session's chain"
        )
    finally:
        os_client.delete_pit(body={"pit_id": [pit]})
    print()


def main() -> int:
    os_client = client()
    excluded = load_excluded_ips(
        os.environ.get("EXCLUDED_IPS_FILE", "/opt/nettap/data/excluded_ips.json")
    )
    print(f"   excluded IPs: {len(excluded)}")
    print()
    # Optional arguments pick windows by hours (verify-figures.sh runs only 24)
    wanted = {int(a) for a in sys.argv[1:] if a.isdigit()}
    base_rss = rss_mb()
    for words, hours in WINDOWS:
        if wanted and hours not in wanted:
            continue
        try:
            verify_window(os_client, words, hours, excluded, base_rss)
        except Exception as exc:  # noqa: BLE001 — report any failure and carry on to the next window
            check(f"last {words}", False, f"{type(exc).__name__}: {exc}")
            print()
    print(
        "=== Every certificate figure matches the recount ==="
        if not FAILED
        else "=== Finished with ✗ lines above — paste this output back ==="
    )
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
