"""In-memory stand-in for OpenSearch search, enough to run detections end to end (#96).

Docs are flat dicts keyed by field name (@timestamp in epoch ms). Composite aggregations page
in key order with `size`/`after` like OpenSearch, terms lists keep only their top `size`, and a
response with more than `max_buckets` buckets is refused like search.max_buckets.
"""

import ipaddress
from datetime import datetime, timezone

UNITS_MS = {"s": 1_000, "m": 60_000, "h": 3_600_000}


class TooManyBuckets(Exception):
    pass


def _ms(interval: str) -> int:
    return int(interval[:-1]) * UNITS_MS[interval[-1]]


def _same(field: str, value, wanted) -> bool:
    if field.endswith(".ip") and isinstance(wanted, str) and "/" in wanted:
        return ipaddress.ip_address(value) in ipaddress.ip_network(wanted)
    return value == wanted


def matches(doc: dict, clause: dict) -> bool:
    if "bool" in clause:
        b = clause["bool"]
        should = b.get("should", [])
        return (
            all(matches(doc, c) for c in b.get("filter", []) + b.get("must", []))
            and not any(matches(doc, c) for c in b.get("must_not", []))
            and (not should or sum(matches(doc, c) for c in should) >= b.get("minimum_should_match", 1))
        )
    if "term" in clause:
        ((field, wanted),) = clause["term"].items()
        return field in doc and _same(field, doc[field], wanted)
    if "terms" in clause:
        ((field, values),) = clause["terms"].items()
        return field in doc and any(_same(field, doc[field], v) for v in values)
    if "range" in clause or "match_all" in clause:
        return True  # test docs all fall inside the requested range
    raise NotImplementedError(clause)


def _group(docs: list[dict], key) -> dict:
    groups: dict = {}
    for d in docs:
        k = key(d)
        if k is not None:
            groups.setdefault(k, []).append(d)
    return groups


class FakeOpenSearch:
    def __init__(self, docs: list[dict], max_buckets: int = 65_535):
        self.docs = docs
        self.max_buckets = max_buckets
        self.bodies: list[dict] = []
        self.bucket_counts: list[int] = []

    def search(self, index=None, body=None, **_):
        self.bodies.append(body)
        docs = [d for d in self.docs if matches(d, body.get("query", {"match_all": {}}))]
        self._buckets = 0
        aggs = {name: self._agg(spec, docs) for name, spec in (body.get("aggs") or {}).items()}
        self.bucket_counts.append(self._buckets)
        if self._buckets > self.max_buckets:
            raise TooManyBuckets(f"{self._buckets} buckets > search.max_buckets {self.max_buckets}")
        return {"hits": {"total": {"value": len(docs)}}, "aggregations": aggs}

    def _bucket(self, extra: dict, docs: list[dict], subs: dict) -> dict:
        self._buckets += 1
        return {**extra, "doc_count": len(docs), **{n: self._agg(s, docs) for n, s in subs.items()}}

    def _agg(self, spec: dict, docs: list[dict]) -> dict:
        subs = spec.get("aggs", {})
        if "composite" in spec:
            return self._composite(spec["composite"], docs, subs)
        if "filters" in spec:
            named = spec["filters"]["filters"]
            return {"buckets": {n: self._bucket({}, [d for d in docs if matches(d, q)], subs) for n, q in named.items()}}
        if "date_histogram" in spec:
            h = spec["date_histogram"]
            step = _ms(h["fixed_interval"])
            groups = _group(docs, lambda d: d[h["field"]] // step * step if h["field"] in d else None)
            return {"buckets": [self._bucket({"key": k}, groups[k], subs) for k in sorted(groups)]}
        if "terms" in spec:
            t = spec["terms"]
            groups = _group(docs, lambda d: d.get(t["field"]))
            top = sorted(groups, key=lambda k: (-len(groups[k]), k))[: t.get("size", 10)]
            return {"doc_count_error_upper_bound": 0, "buckets": [self._bucket({"key": k}, groups[k], subs) for k in top]}
        if "filter" in spec:
            kept = [d for d in docs if matches(d, spec["filter"])]
            return {"doc_count": len(kept), **{n: self._agg(s, kept) for n, s in subs.items()}}
        if "cardinality" in spec:
            return {"value": len({d[spec["cardinality"]["field"]] for d in docs if spec["cardinality"]["field"] in d})}
        if "value_count" in spec:
            return {"value": sum(spec["value_count"]["field"] in d for d in docs)}
        for op in ("min", "max"):
            if op in spec:
                values = [d[spec[op]["field"]] for d in docs if spec[op]["field"] in d]
                v = (min if op == "min" else max)(values) if values else None
                as_string = datetime.fromtimestamp(v / 1000, tz=timezone.utc).isoformat() if v is not None else None
                return {"value": v, "value_as_string": as_string}
        raise NotImplementedError(spec)

    def _composite(self, c: dict, docs: list[dict], subs: dict) -> dict:
        names = [next(iter(s)) for s in c["sources"]]

        def key(d: dict):
            values = []
            for s in c["sources"]:
                ((_, src),) = s.items()
                if "terms" in src:
                    value = d.get(src["terms"]["field"])
                else:
                    field, step = src["date_histogram"]["field"], _ms(src["date_histogram"]["fixed_interval"])
                    value = d[field] // step * step if field in d else None
                if value is None:
                    return None
                values.append(value)
            return tuple(values)

        groups = _group(docs, key)
        after = tuple(c["after"][n] for n in names) if c.get("after") else None
        page = [k for k in sorted(groups) if after is None or k > after][: c["size"]]
        buckets = [self._bucket({"key": dict(zip(names, k))}, groups[k], subs) for k in page]
        return {"buckets": buckets, **({"after_key": dict(zip(names, page[-1]))} if page else {})}
