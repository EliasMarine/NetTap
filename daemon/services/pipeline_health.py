"""Is current data arriving? (F2, release audit 2026-11)

/api/system/health checked storage, SMART and an OpenSearch ping only, so with Zeek, Suricata,
Logstash or Filebeat stopped, or nothing new indexed, health stayed green and pages said
"No actionable alerts detected". This probe answers two questions within one 5 s budget:

- How old is the newest Zeek record OpenSearch has indexed? max(event.ingested), not
  @timestamp: @timestamp is when a connection started, so a long one indexed now can be days old.
- Are the four sensor containers running? One ``docker inspect``.

The answer is cached for 30 s, and concurrent callers share one probe.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from opensearchpy import OpenSearch

logger = logging.getLogger("nettap.pipeline_health")

NETWORK_INDEX = os.environ.get("OPENSEARCH_NETWORK_INDEX", "arkime_sessions3-*")
SENSORS = (
    "nettap-zeek-live",
    "nettap-suricata-live",
    "nettap-logstash",
    "nettap-filebeat",
)
INSPECT_CMD = ["docker", "inspect", "--format", "{{.Name}} {{.State.Status}}", *SENSORS]

THRESHOLD_S = 900  # newest record older than 15 min: stale
GRACE_S = 600  # no record while the daemon is up 10 min or less: still starting
BUDGET_S = 5.0  # the search and docker inspect together; whatever is late reads unknown
CACHE_S = 30.0
UNKNOWN_CACHE_S = 5.0  # a check that couldn't run is tried again sooner
# The client the caller builds for this probe has timeout=3 and max_retries=0, so the search
# thread ends on its own inside the budget.

# state -> effect on the overall health (server._aggregate_health)
OVERALL = {
    "fresh": None,
    "stale": "problem",
    "no_data": "problem",
    "sensor_stopped": "problem",
    "starting": "incomplete",
    "unknown": "incomplete",
}

_NEWEST_QUERY = {
    "size": 0,
    "query": {
        "bool": {
            "filter": [
                {"term": {"event.provider": "zeek"}},
                {"range": {"event.ingested": {"gte": "now-7d"}}},
            ]
        }
    },
    "aggs": {"newest": {"max": {"field": "event.ingested"}}},
}

# `docker inspect a b c` with b missing (Docker 29, checked 2026-11-08) prints a's and c's
# lines on stdout, "error: no such object: b" on stderr, and exits 1. Older CLIs write
# "Error: No such object: b". So a name is read from what was printed, never from the exit code.
_NO_SUCH = re.compile(r"no such object: (\S+)", re.IGNORECASE)


def parse_inspect(stdout: str, stderr: str) -> dict[str, str]:
    """{container: status}: "missing" when docker said it doesn't exist, "unknown" when it didn't say."""
    seen = {}
    for line in stdout.splitlines():
        name, _, status = line.strip().partition(" ")
        if status:
            seen[name.lstrip("/")] = status
    missing = set(_NO_SUCH.findall(stderr))
    return {
        name: seen.get(name) or ("missing" if name in missing else "unknown")
        for name in SENSORS
    }


def classify(
    age_s: float | None, search_ok: bool, sensors: dict[str, str], daemon_up_s: float
) -> str:
    """The state table (PLAN.md F2); age_s is None when no record was found. A known problem wins
    over a check that couldn't run."""
    if any(s not in ("running", "unknown") for s in sensors.values()):
        return "sensor_stopped"
    if search_ok and age_s is not None and age_s > THRESHOLD_S:
        return "stale"
    if search_ok and age_s is None and daemon_up_s > GRACE_S:
        return "no_data"
    if not search_ok or "unknown" in sensors.values():
        return "unknown"
    return "starting" if age_s is None else "fresh"


class PipelineHealth:
    """Freshness of the newest record plus the sensors' state, cached 30 s, one probe at a time."""

    def __init__(self, client: OpenSearch, start_time: float):
        self._client = client  # built with timeout=3, max_retries=0
        self._start_time = start_time  # time.monotonic() when the daemon started
        self._task: asyncio.Task | None = None
        self._result: dict | None = None
        self._result_at = 0.0
        # Its own thread (review): on the shared route pool, time queued behind a cold page load
        # counted against the budget and read as "couldn't check".
        self._pool = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="pipeline-health"
        )

    async def get(self) -> dict:
        if self._result:
            ttl = UNKNOWN_CACHE_S if self._result["state"] == "unknown" else CACHE_S
            if time.monotonic() - self._result_at < ttl:
                return self._result
        # Replaced only once finished, so concurrent callers share the one in flight; shield
        # keeps a caller that gives up (a closed request) from cancelling it for the others.
        if self._task is None or self._task.done():
            self._task = asyncio.ensure_future(self._probe())
        return await asyncio.shield(self._task)

    async def _probe(self) -> dict:
        search = asyncio.get_running_loop().run_in_executor(self._pool, self._newest_ms)
        inspect = asyncio.ensure_future(self._sensors())
        _, late = await asyncio.wait({search, inspect}, timeout=BUDGET_S)
        for task in late:
            task.cancel()  # the docker child is killed and reaped in _sensors
        if late:
            await asyncio.wait(late)

        newest_ms, search_ok = None, False
        if search in late:
            logger.warning(
                "Pipeline health: the freshness search took longer than %s s", BUDGET_S
            )
        elif search.exception():
            logger.warning(
                "Pipeline health: freshness search failed: %s", search.exception()
            )
        else:
            newest_ms, search_ok = search.result(), True

        sensors = dict.fromkeys(SENSORS, "unknown")
        if inspect in late:
            logger.warning(
                "Pipeline health: docker inspect took longer than %s s", BUDGET_S
            )
        elif inspect.exception():
            logger.warning(
                "Pipeline health: docker inspect failed: %s", inspect.exception()
            )
        else:
            sensors = inspect.result()

        now = time.time()
        found = newest_ms is not None
        age_s = max(0.0, now - newest_ms / 1000) if found else None
        result = {
            "state": classify(
                age_s, search_ok, sensors, time.monotonic() - self._start_time
            ),
            "newest_record_at": (
                datetime.fromtimestamp(newest_ms / 1000, timezone.utc).isoformat()
                if found
                else None
            ),
            "age_seconds": round(age_s) if found else None,
            "threshold_seconds": THRESHOLD_S,
            "sensors": sensors,
            "checked_at": datetime.fromtimestamp(now, timezone.utc).isoformat(),
        }
        self._result, self._result_at = result, time.monotonic()
        return result

    def _newest_ms(self) -> float | None:
        """Epoch ms of the newest Zeek record indexed in the last 7 days; None when there is none."""
        resp = self._client.search(index=NETWORK_INDEX, body=_NEWEST_QUERY)
        return resp.get("aggregations", {}).get("newest", {}).get("value")

    async def _sensors(self) -> dict[str, str]:
        proc = await asyncio.create_subprocess_exec(
            *INSPECT_CMD, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            out, err = await proc.communicate()
        finally:
            if (
                proc.returncode is None
            ):  # cancelled at the deadline: kill and reap the child
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                await proc.wait()
        return parse_inspect(out.decode(errors="replace"), err.decode(errors="replace"))
