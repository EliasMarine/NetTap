"""Every search of one request over one point-in-time snapshot, checked (NET-154, NET-160).

Extracted from the certificate pass (services/cert_overview.py) so the drill-down pages use
the same guards. A figure is complete or the request fails: a timed-out reply, a failed
shard, a missing aggregation or a malformed reply raises QueryFailed, never a smaller count.
Lists come from composite aggregations paged over the same snapshot, so every page and every
total sees the same data, and a list cut by its cap says so (`complete` False).
"""

import logging
import os
import time
from typing import Any, Callable

from opensearchpy import OpenSearchException

logger = logging.getLogger("nettap.storage.snapshot_search")

NETWORK_INDEX = os.environ.get("OPENSEARCH_NETWORK_INDEX", "arkime_sessions3-*")

PIT_CLOSE_SECONDS = (
    5  # closing runs in `finally`, often when OpenSearch is already slow
)
GROUP_PAGE = 1_000
MAX_GROUP_BUCKETS = 100_000
# Per-bucket metrics only: a nested terms agg could be cut without saying so
_METRICS = {"sum", "max", "min", "value_count"}


class QueryFailed(Exception):
    """A query failed or was incomplete; never show partial figures as counts (#96)."""


class TooSlow(QueryFailed):
    """The request ran past its time budget."""


class Budget:
    """One monotonic deadline for a whole request: queueing, searches and encoding."""

    def __init__(
        self, seconds: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._clock = clock
        self._end = clock() + seconds

    def remaining(self) -> float:
        return self._end - self._clock()

    def check(self, what: str) -> None:
        if self.remaining() <= 0:
            raise TooSlow(f"{what} took too long")


def checked(reply: Any, what: str, required: tuple[str, ...] = ()) -> dict:
    """A complete, well-formed reply holding every `required` aggregation, or QueryFailed."""
    if not isinstance(reply, dict):
        raise QueryFailed(f"{what}: malformed reply")
    if reply.get("timed_out"):
        raise QueryFailed(f"{what} timed out")
    shards = reply.get("_shards")
    if isinstance(shards, dict) and shards.get("failed"):
        raise QueryFailed(f"{what}: {shards.get('failed')} shard(s) failed")
    aggs = reply.get("aggregations")
    if required and (
        not isinstance(aggs, dict)
        or any(not isinstance(aggs.get(n), dict) for n in required)
    ):
        raise QueryFailed(f"{what}: missing aggregation")
    return reply


def search(client: Any, body: dict, budget: Budget, what: str) -> dict:
    """One search with the budget's remainder as its timeout, checked."""
    budget.check(what)
    timeout = max(1.0, budget.remaining())
    body = {**body, "timeout": f"{int(timeout * 1000)}ms"}
    try:
        reply = client.search(body=body, request_timeout=timeout)
    except OpenSearchException as exc:
        logger.error("Failed to query %s: %s", what, exc)
        raise QueryFailed(f"{what} query failed") from exc
    return checked(reply, what)


def open_pit(client: Any, index: str, keep_alive: str, budget: Budget) -> str:
    budget.check("opening a snapshot")
    try:
        # A partial snapshot would silently drop the failed shards' records from every count
        reply = client.create_pit(
            index=index,
            keep_alive=keep_alive,
            allow_partial_pit_creation="false",
            request_timeout=max(1.0, budget.remaining()),
        )
    except OpenSearchException as exc:
        logger.error("Failed to open a point in time: %s", exc)
        raise QueryFailed("snapshot failed") from exc
    pit = checked(reply, "snapshot").get("pit_id")
    if not pit:
        raise QueryFailed("snapshot failed: no pit_id")
    return str(pit)


def close_pit(client: Any, pit: str) -> None:
    try:
        client.delete_pit(body={"pit_id": [pit]}, request_timeout=PIT_CLOSE_SECONDS)
    except (
        OpenSearchException
    ) as exc:  # it expires on its own; the figures are already safe
        logger.warning("Couldn't close point in time: %s", exc)


def total_hits(reply: dict, what: str) -> int:
    """hits.total of a track_total_hits search, exact or QueryFailed."""
    total = (reply.get("hits") or {}).get("total")
    if (
        not isinstance(total, dict)
        or total.get("relation", "eq") != "eq"
        or not isinstance(total.get("value"), int)
    ):
        raise QueryFailed(f"{what}: no exact total")
    return total["value"]


def doc_count(agg: Any, what: str) -> int:
    count = agg.get("doc_count") if isinstance(agg, dict) else None
    if not isinstance(count, int):
        raise QueryFailed(f"{what}: malformed aggregation")
    return count


def metric(agg: dict, name: str, what: str) -> Any:
    """A metric's value (None for a max/min over no records), or QueryFailed when absent."""
    m = agg.get(name)
    if not isinstance(m, dict) or "value" not in m:
        raise QueryFailed(f"{what}: missing {name}")
    return m["value"]


class SnapshotSearch:
    """`with SnapshotSearch(client, index, budget) as snap:` — every search on one PIT."""

    def __init__(
        self, client: Any, index: str, budget: Budget, keep_alive: str = "30s"
    ) -> None:
        self._client = client
        self._index = index
        self._budget = budget
        self._keep_alive = keep_alive
        self._pit: str | None = None

    def __enter__(self) -> "SnapshotSearch":
        self._pit = open_pit(self._client, self._index, self._keep_alive, self._budget)
        return self

    def __exit__(self, *_exc: Any) -> None:
        if self._pit:
            close_pit(self._client, self._pit)
            self._pit = None

    def search(self, body: dict, what: str, required: tuple[str, ...] = ()) -> dict:
        body = {**body, "pit": {"id": self._pit, "keep_alive": self._keep_alive}}
        reply = checked(search(self._client, body, self._budget, what), what, required)
        self._pit = reply.get("pit_id") or self._pit
        return reply

    def count(self, query: dict, what: str) -> int:
        body = {"size": 0, "track_total_hits": True, "query": query}
        return total_hits(self.search(body, what), what)

    def groups(
        self,
        query: dict,
        sources: list[dict],
        metrics: dict | None,
        what: str,
        max_buckets: int | None = None,
    ) -> tuple[list[dict], bool]:
        """(every composite bucket for `sources`, False if the cap stopped the paging)."""
        cap = MAX_GROUP_BUCKETS if max_buckets is None else max_buckets
        if any(next(iter(m)) not in _METRICS for m in (metrics or {}).values()):
            raise ValueError("groups takes per-bucket metrics only")
        buckets: list[dict] = []
        after = None
        while True:
            composite: dict = {"size": GROUP_PAGE, "sources": sources}
            if after is not None:
                composite["after"] = after
            agg: dict = {"composite": composite}
            if metrics:
                agg["aggs"] = metrics
            body = {"size": 0, "query": query, "aggs": {"groups": agg}}
            page = self.search(body, what, ("groups",))["aggregations"]["groups"]
            got = page.get("buckets")
            if not isinstance(got, list):
                raise QueryFailed(f"{what}: malformed aggregation")
            buckets.extend(got)
            after = page.get("after_key")
            # a composite fills every page it can, so a short page is the last one
            if len(got) < GROUP_PAGE or after is None:
                return buckets, True
            if len(buckets) >= cap:
                return buckets, False
