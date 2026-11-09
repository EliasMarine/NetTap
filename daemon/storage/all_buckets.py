"""Every bucket of a grouping, however many there are (#96).

A terms aggregation returns its top `size` buckets; code that sums, counts or scans them as
"all" goes wrong once a network has more distinct values than that. A composite aggregation
pages through every bucket in key order, so it is the tool for complete sets.
"""

from typing import Any

from storage.exact_terms import PartialResultsError
from storage.snapshot_search import QueryFailed, checked

PAGE_SIZE = 1_000
# shortcut: stops after this many buckets and reports complete=False; raise it if a site needs more
MAX_BUCKETS = 500_000


def all_buckets(
    client: Any,
    index: str,
    query: dict,
    sources: list[dict],
    aggs: dict | None = None,
    page_size: int = PAGE_SIZE,
    max_buckets: int = MAX_BUCKETS,
    what: str | None = None,
) -> tuple[list[dict], bool]:
    """(every composite bucket for `sources`, with `aggs` per bucket; False if max_buckets stopped it).

    `sources` are composite sources, e.g. [{"ip": {"terms": {"field": "source.ip"}}}]; each
    bucket's "key" is a dict keyed by those names. With `what`, every page is checked: a timed
    out, partly failed or aggregation-less reply raises QueryFailed instead of reading as fewer.
    """
    buckets: list[dict] = []
    after = None
    while True:
        composite: dict = {"size": page_size, "sources": sources}
        if after is not None:
            composite["after"] = after
        agg: dict = {"composite": composite}
        if aggs:
            agg["aggs"] = aggs
        reply = client.search(
            index=index, body={"size": 0, "query": query, "aggs": {"all": agg}}
        )
        if what is not None:
            reply = checked(reply, what, ("all",))
        page = (reply.get("aggregations") or {}).get("all") or {}
        # OLD CODE START — a reply with an after_key and no bucket list paged forever, and a
        # short last page cost one more (empty) search
        # buckets = [*buckets, *page.get("buckets", [])]
        # after = page.get("after_key")
        # if not page.get("buckets") or after is None:
        #     return buckets, True
        # OLD CODE END
        got = page.get("buckets")
        after = page.get("after_key")
        # a checked read never takes a malformed page, or a full one with no next key, as the end
        if what is not None and (
            not isinstance(got, list) or (len(got) >= page_size and after is None)
        ):
            raise QueryFailed(f"{what}: malformed page")
        got = got if isinstance(got, list) else []
        buckets = [*buckets, *got]
        # a composite fills every page it can, so a short page is the last one
        if len(got) < page_size or after is None:
            return buckets, True
        if len(buckets) >= max_buckets:
            return buckets, False


def complete_terms(
    client: Any,
    index: str,
    query: dict,
    terms_reply: dict,
    source: dict,
    aggs: dict | None = None,
    missing: Any = None,
) -> list[dict]:
    """A terms aggregation's buckets when they hold every value, else every value paged (#96).

    `sum_other_doc_count` 0 means no record fell outside the returned buckets, so the top list is
    the whole set (one search, the usual case). Otherwise `source` (a composite source on the same
    field) pages every value; buckets come back in terms form, the key flattened and a missing
    value (null) read as `missing`, as the terms aggregation's own `missing` would.
    """
    if not terms_reply.get("sum_other_doc_count"):
        return terms_reply.get("buckets", [])
    # OLD CODE START — NET-237: the flag was dropped, so a capped scan read as every value
    # buckets, _complete = all_buckets(
    #     client, index, query, [{"value": source}], aggs=aggs
    # )
    # OLD CODE END
    buckets, complete = all_buckets(
        client, index, query, [{"value": source}], aggs=aggs
    )
    if not complete:
        field = (source.get("terms") or {}).get("field")
        raise PartialResultsError(f"{field} values stopped at {len(buckets)}")
    return [
        {**b, "key": missing if b["key"]["value"] is None else b["key"]["value"]}
        for b in buckets
    ]
