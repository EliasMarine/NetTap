"""Every bucket of a grouping, however many there are (#96).

A terms aggregation returns its top `size` buckets; code that sums, counts or scans them as
"all" goes wrong once a network has more distinct values than that. A composite aggregation
pages through every bucket in key order, so it is the tool for complete sets.
"""

from typing import Any

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
) -> tuple[list[dict], bool]:
    """(every composite bucket for `sources`, with `aggs` per bucket; False if max_buckets stopped it).

    `sources` are composite sources, e.g. [{"ip": {"terms": {"field": "source.ip"}}}]; each
    bucket's "key" is a dict keyed by those names.
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
        reply = client.search(index=index, body={"size": 0, "query": query, "aggs": {"all": agg}})
        page = (reply.get("aggregations") or {}).get("all") or {}
        # OLD CODE START — a reply with an after_key and no bucket list paged forever, and a
        # short last page cost one more (empty) search
        # buckets = [*buckets, *page.get("buckets", [])]
        # after = page.get("after_key")
        # if not page.get("buckets") or after is None:
        #     return buckets, True
        # OLD CODE END
        got = page.get("buckets")
        got = got if isinstance(got, list) else []
        buckets = [*buckets, *got]
        after = page.get("after_key")
        # a composite fills every page it can, so a short page is the last one
        if len(got) < page_size or after is None:
            return buckets, True
        if len(buckets) >= max_buckets:
            return buckets, False
