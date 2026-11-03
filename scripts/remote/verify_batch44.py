"""Batch 44 checks: LAN subnets are re-detected hourly (#116) without changing on their own.

Runs inside nettap-storage-daemon (deploy-data-accuracy-batch44.sh passes it with `python3 -c`).
Read-only. The G11 can't grow a new subnet on demand; the unit test covers that path. This
checks the hourly re-detection on real data: it finds the startup subnets, so the filter
doesn't change by itself, and it is cheap enough to run every hour.
"""

import os
import sys
import time

PROBLEMS: list[str] = []


def check(label: str, ok: bool, detail: str) -> None:
    print(f"{'✓' if ok else '✗'} {label}: {detail}")
    if not ok:
        PROBLEMS.append(label)


def main() -> int:
    sys.path.insert(0, "/opt/nettap/daemon")
    from main import _parse_curlrc_credentials
    from opensearchpy import OpenSearch  # only inside the daemon container
    from services.excluded_ips import (
        build_lan_filter,
        changed_lan_filter,
        detect_lan_subnets,
    )

    client = OpenSearch(os.environ["OPENSEARCH_URL"], verify_certs=False, ssl_show_warn=False, timeout=120,
                        http_auth=_parse_curlrc_credentials(os.environ["OPENSEARCH_CREDS_CONFIG_FILE"]))
    manual = os.environ.get("LAN_SUBNETS", "").strip()
    t0 = time.time()
    subnets = detect_lan_subnets(client)
    took = round(time.time() - t0, 2)
    named = ", ".join(f"{a}.{b}.{c}.0/24" for a, b, c in subnets)
    check("LAN detection runs on real data", bool(subnets) and took < 30, f"{named or 'none'} in {took} s; LAN_SUBNETS {manual or 'not set'}")
    same = changed_lan_filter(client, build_lan_filter(subnets))
    check("re-detection leaves unchanged subnets alone", same is None, "no change" if same is None else "reported a change")
    print(f"RESULT {len(PROBLEMS)}")
    return 1 if PROBLEMS else 0


if __name__ == "__main__":
    sys.exit(main())
