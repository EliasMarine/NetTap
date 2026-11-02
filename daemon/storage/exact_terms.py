"""OpenSearch client whose terms aggregations count exactly across daily indices (#93).

A search over several daily indices counts each index's top `shard_size` terms (default
size * 1.5 + 10) and merges them, so a term outside one day's list loses that day's count:
on the G11, with the data split, Log Explorer's top talker #8 read 38,678 for 40,046. Asking
every shard for up to EXACT_SHARD_SIZE terms makes the merge see every term of a day.
"""

from typing import Any

from opensearchpy import OpenSearch

# shortcut: exact while one day holds at most this many terms per list (a home network's
# destinations, domains and pairs); a busier day's tail is approximate again — raise it then
EXACT_SHARD_SIZE = 10_000


def with_exact_terms(aggs: dict) -> dict:
    """A copy of `aggs` in which every terms aggregation without a shard_size gets one."""
    out: dict = {}
    for name, agg in aggs.items():
        if not isinstance(agg, dict):
            out[name] = agg
            continue
        new = dict(agg)
        terms = agg.get("terms")
        if isinstance(terms, dict) and "shard_size" not in terms:
            new["terms"] = {**terms, "shard_size": max(EXACT_SHARD_SIZE, int(terms.get("size", 10)))}
        for key in ("aggs", "aggregations"):
            if isinstance(agg.get(key), dict):
                new[key] = with_exact_terms(agg[key])
        out[name] = new
    return out


def exact_body(body: Any) -> Any:
    """A search body with exact terms aggregations (anything else is returned unchanged)."""
    if not isinstance(body, dict):
        return body
    for key in ("aggs", "aggregations"):
        if isinstance(body.get(key), dict):
            body = {**body, key: with_exact_terms(body[key])}
    return body


class ExactTermsOpenSearch(OpenSearch):
    """The daemon's OpenSearch client: search and msearch bodies get exact terms counts."""

    def search(self, *, body: Any = None, **kwargs: Any) -> Any:
        return super().search(body=exact_body(body), **kwargs)

    def msearch(self, *, body: Any = None, **kwargs: Any) -> Any:
        if isinstance(body, list):
            body = [exact_body(b) for b in body]
        return super().msearch(body=body, **kwargs)
