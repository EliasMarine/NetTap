"""OpenSearch client whose terms aggregations count exactly across daily indices (#93).

A search over several daily indices counts each index's top `shard_size` terms (default
size * 1.5 + 10) and merges them, so a term outside one day's list loses that day's count:
on the G11, with the data split, Log Explorer's top talker #8 read 38,678 for 40,046.
Every terms aggregation asks each shard for up to EXACT_SHARD_SIZE terms. OpenSearch reports
`doc_count_error_upper_bound` != 0 on any list a shard cut short (> 0 by count, -1 when
ordered by a metric), so a busier network's search is re-run with longer lists (#94).
"""

import logging
from typing import Any

from opensearchpy import OpenSearch, OpenSearchException

logger = logging.getLogger("nettap.opensearch")

# Holds every term of a day on a home network; a search with longer lists is re-run x10
EXACT_SHARD_SIZE = 10_000
# Past this the counts stay OpenSearch's estimate and a warning is logged (memory bound)
MAX_SHARD_SIZE = 100_000


def with_exact_terms(aggs: dict, shard_size: int = EXACT_SHARD_SIZE) -> dict:
    """A copy of `aggs` in which every terms aggregation asks each shard for >= shard_size terms."""
    out: dict = {}
    for name, agg in aggs.items():
        if not isinstance(agg, dict):
            out[name] = agg
            continue
        new = dict(agg)
        for kind in ("terms", "multi_terms"):  # multi_terms: beacon candidates (#96)
            terms = agg.get(kind)
            if isinstance(terms, dict):
                wanted = max(
                    shard_size,
                    int(terms.get("size", 10)),
                    int(terms.get("shard_size", 0)),
                )
                new[kind] = {**terms, "shard_size": wanted}
        for key in ("aggs", "aggregations"):
            if isinstance(agg.get(key), dict):
                new[key] = with_exact_terms(agg[key], shard_size)
        out[name] = new
    return out


def exact_body(body: Any, shard_size: int = EXACT_SHARD_SIZE) -> Any:
    """A search body with exact terms aggregations (anything else is returned unchanged)."""
    if not isinstance(body, dict):
        return body
    for key in ("aggs", "aggregations"):
        if isinstance(body.get(key), dict):
            body = {**body, key: with_exact_terms(body[key], shard_size)}
    return body


def truncated(node: Any) -> bool:
    """True if any terms list in an aggregations reply was cut short by a shard."""
    if isinstance(node, dict):
        if node.get("doc_count_error_upper_bound", 0) != 0:
            return True
        return any(truncated(v) for v in node.values() if isinstance(v, (dict, list)))
    if isinstance(node, list):
        return any(truncated(v) for v in node)
    return False


def _any_truncated(reply: Any) -> bool:
    if not isinstance(reply, dict):
        return False
    if "responses" in reply:  # msearch
        return any(
            truncated(r.get("aggregations"))
            for r in reply["responses"]
            if isinstance(r, dict)
        )
    return truncated(reply.get("aggregations"))


class PartialResultsError(OpenSearchException):
    """Some shards failed, the search timed out or a scan hit its cap: the reply is only part of the data."""


def _failed_shards(reply: Any) -> int:
    """Shards that failed in a search or msearch reply (OpenSearch still answers from the rest)."""
    if not isinstance(reply, dict):
        return 0
    if "responses" in reply:
        return sum(_failed_shards(r) for r in reply["responses"])
    shards = reply.get("_shards")
    return int(shards.get("failed", 0) or 0) if isinstance(shards, dict) else 0


def _partial(reply: Any) -> str | None:
    """Why a search, msearch or count reply covers only part of the data, or None (NET-237)."""
    if not isinstance(reply, dict):
        return None
    if "responses" in reply:  # msearch: one failed or partial search spoils the batch
        return next((why for r in reply["responses"] if (why := _partial(r))), None)
    if reply.get("error"):
        return "a search in the batch failed"
    # a timed-out search answers from the shards that finished in time
    if reply.get("timed_out"):
        return "the search timed out"
    if failed := _failed_shards(reply):
        return f"{failed} shard(s) failed"
    return None


def _raise_if_partial(reply: Any, kwargs: dict) -> None:
    if why := _partial(reply):
        raise PartialResultsError(
            f"{why} on {kwargs.get('index', '?')}; the reply is partial"
        )


class ExactTermsOpenSearch(OpenSearch):
    """The daemon's OpenSearch client: search and msearch bodies get exact terms counts."""

    def _exact(self, send, body: Any, **kwargs: Any) -> Any:
        shard_size = EXACT_SHARD_SIZE
        while True:
            reply = send(body=body, shard_size=shard_size, **kwargs)
            # By default OpenSearch answers from the shards that worked; a figure from part of the
            # data must be an error, not a smaller number
            # OLD CODE START — NET-237: a timed-out search, or a failed search inside an msearch,
            # still read as a complete answer
            # if failed := _failed_shards(reply):
            #     raise PartialResultsError(
            #         f"{failed} shard(s) failed on {kwargs.get('index', '?')}; the reply is partial"
            #     )
            # OLD CODE END
            _raise_if_partial(reply, kwargs)
            if not _any_truncated(reply):
                return reply
            if shard_size >= MAX_SHARD_SIZE:
                logger.warning(
                    "A terms list on %s still has more terms than %d per shard; its counts are estimates",
                    kwargs.get("index", "?"),
                    shard_size,
                )
                return reply
            shard_size = min(shard_size * 10, MAX_SHARD_SIZE)

    def search(self, *, body: Any = None, **kwargs: Any) -> Any:
        def send(body: Any, shard_size: int, **kw: Any) -> Any:
            return super(ExactTermsOpenSearch, self).search(
                body=exact_body(body, shard_size), **kw
            )

        return self._exact(send, body, **kwargs)

    def msearch(self, *, body: Any = None, **kwargs: Any) -> Any:
        def send(body: Any, shard_size: int, **kw: Any) -> Any:
            if isinstance(body, list):
                body = [exact_body(b, shard_size) for b in body]
            return super(ExactTermsOpenSearch, self).msearch(body=body, **kw)

        return self._exact(send, body, **kwargs)

    def count(self, *, body: Any = None, **kwargs: Any) -> Any:
        # NET-237: a count answers from the shards that worked too
        reply = super().count(body=body, **kwargs)
        _raise_if_partial(reply, kwargs)
        return reply
