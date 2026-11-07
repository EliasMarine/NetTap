"""NET-192 PR 2: the daemon keeps answering while pages load.

Runs inside nettap-storage-daemon (python3 -c "$(cat ...)"). Five Home pages load at once
(the 15 calls the Home page makes, 24 h); meanwhile a separate process asks /api/health every
0.25 s (in this process its timings would include waiting on the 75 client threads).
Prints one line: health's slowest answer, failed page calls, the slowest page call.
Exit 1 if health ever took longer than 1 s or a page call failed.
"""

import multiprocessing
import statistics
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

BASE = "http://localhost:8880"
TOKEN = open("/run/nettap-auth/daemon-token").read().strip()
HOMES = 5
HEALTH_LIMIT_S = 1.0


def stamp(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


now = datetime.now(UTC)
win = {"from": stamp(now - timedelta(days=1)), "to": stamp(now)}
prev = {"from": stamp(now - timedelta(days=2)), "to": win["from"]}


def q(params):
    return "?" + urllib.parse.urlencode(params)


# The Home page's calls (web/src/routes/+page.svelte load()).
HOME = [
    "/api/traffic/summary" + q(win),
    "/api/traffic/summary" + q(prev),
    "/api/traffic/bandwidth" + q({**win, "interval": "1h"}),
    "/api/traffic/protocols" + q(win),
    "/api/traffic/categories" + q(win),
    "/api/devices/count" + q(win),
    "/api/devices/registry/new-count" + q({"since": win["from"]}),
    "/api/alerts/count" + q(win),
    "/api/alerts/count" + q(prev),
    "/api/system/health",
    "/api/alerts/smart" + q({**win, "limit": 10}),
    "/api/alerts/smart/summary" + q(win),
    "/api/devices" + q({**win, "sort": "bytes", "order": "desc", "limit": 8}),
    "/api/capture/health",
    "/api/capture/stats",
]


def call(path, timeout=120):
    t0 = time.monotonic()
    try:
        req = urllib.request.Request(
            BASE + path, headers={"X-NetTap-Daemon-Token": TOKEN}
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read()
            ok = r.status == 200
    except Exception:
        ok = False
    return ok, time.monotonic() - t0, path.split("?")[0]


def watch_health(done, health):
    while not done.is_set():
        ok, secs, _ = call("/api/health", timeout=30)
        health.append(secs if ok else 30.0)
        time.sleep(0.25)


if __name__ == "__main__":
    with multiprocessing.Manager() as mgr:
        done, health = mgr.Event(), mgr.list()
        watcher = multiprocessing.Process(target=watch_health, args=(done, health))
        watcher.start()
        time.sleep(1)  # a few unloaded answers first
        with ThreadPoolExecutor(max_workers=HOMES * len(HOME)) as pool:
            results = list(pool.map(call, HOME * HOMES))
        done.set()
        watcher.join()
        health = list(health)

    failed = sorted({p for ok, _, p in results if not ok})
    slowest = max(results, key=lambda r: r[1])
    worst_health = max(health, default=30.0)
    print(
        f"health slowest {worst_health:.2f} s, median {statistics.median(health or [30.0]):.2f} s over {len(health)} asks; "
        f"{len(results) - sum(ok for ok, _, _ in results)} of {len(results)} page calls failed"
        + (f" ({', '.join(failed)})" if failed else "")
        + f"; slowest page call {slowest[2]} {slowest[1]:.1f} s"
    )
    sys.exit(0 if worst_health < HEALTH_LIMIT_S and not failed else 1)
