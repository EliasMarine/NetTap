"""#139 check, run inside nettap-storage-daemon: the liveness check answers while slow pages run.

Each slow endpoint is requested over 24 h and 30 days; one second in, /api/health is timed.
Before the fix it waited for the slow request (5-13 s) and the top bar's 5 s check gave up.
Read-only: GET requests to the daemon only.
"""

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

HEALTH_LIMIT_S = 1.0
REPORT_BUDGET_S = 10.0
with open("/run/nettap-auth/daemon-token") as token_file:
    TOKEN = token_file.read().strip()


def get(path: str, query: str = "") -> tuple[int, float, bytes]:
    url = "http://localhost:8880" + path + query
    started = time.time()
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, headers={"X-NetTap-Daemon-Token": TOKEN}),
            timeout=300,
        ) as reply:
            code, body = reply.status, reply.read()
    except urllib.error.HTTPError as exc:
        code, body = exc.code, exc.read()
    except Exception as exc:  # noqa: BLE001 — any failure is reported, not hidden
        code, body = 0, str(exc).encode()
    return code, round(time.time() - started, 2), body


def check(label: str, ok: bool, detail: str) -> bool:
    print(f"{'✓' if ok else '✗'} {label}: {detail}")
    return ok


now = datetime.now(UTC)
all_ok = True
for days in (1, 30):
    query = "?" + urllib.parse.urlencode(
        {
            "from": (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "to": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    )
    for path in ("/api/threats/report", "/api/risk/scores", "/api/threats/beaconing"):
        with ThreadPoolExecutor(1) as pool:
            slow = pool.submit(get, path, query)
            time.sleep(1)
            h_code, h_took, _ = get("/api/health")
            code, took, body = slow.result()
        overlapped = took > 1 + h_took
        detail = f"{code} in {took} s; /api/health {h_code} in {h_took} s meanwhile"
        if not overlapped:
            detail += " (finished too fast to overlap)"
        ok = code == 200 and h_code == 200 and h_took < HEALTH_LIMIT_S
        if path == "/api/threats/report" and code == 200:
            report = json.loads(body)
            failed = report.get("failed_checks")
            ok = ok and not failed and took < REPORT_BUDGET_S
            detail += (
                f"; failed checks {failed}, partial {report.get('incomplete_checks')},"
                f" {len(report.get('beaconing', []))} beacon suspects"
            )
        all_ok = check(f"{path} ({days} d)", ok, detail) and all_ok

sys.exit(0 if all_ok else 1)
