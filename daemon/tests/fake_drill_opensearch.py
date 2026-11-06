"""Raw documents behind the calls a drill-down makes (NET-160).

A small evaluator for the query and aggregation shapes the drill-downs send, so their
counts are checked against what OpenSearch would answer, not against canned replies:

- queries: bool (filter/must/should/must_not, minimum_should_match), term (with
  case_insensitive), terms (CIDRs match IPs), range on @timestamp, exists, prefix,
  wildcard, match_all;
- aggregations: filter, sum/min/max/value_count, terms (with size and
  sum_other_doc_count), composite (paged with `after`, with missing_bucket, one bucket per
  value of a multi-valued field) and date_range;
- hits.total exact with track_total_hits, else stopped at 10,000 as OpenSearch does.

create_pit freezes a copy of the documents and every search reads that copy, so a test can
change `docs` between searches and see the snapshot hold. Documents are flat:
{"source.ip": "…", "@timestamp": "…"}; a list value is a multi-valued field.
`tamper(body, reply)` can change or break any reply.

`mapping_types` sets how a field is mapped: a type, {"type", "ignore_above"}, None
(unmapped), or {index: one of those} per index of `index_names` (missing: unmapped there).
A field not set is keyword, except `f.keyword`, which is absent unless set. Searches see
documents as the first index maps them: unmapped fields gone, values longer than
ignore_above dropped, a set `f.keyword` holding `f`'s values (NET-178).
"""

import copy
import fnmatch
import ipaddress
import itertools
from datetime import datetime, timezone

from aiohttp import web

from api.daemon_auth import TOKEN_HEADER, make_auth_middleware

FROM, TO = "2026-11-05T00:00:00Z", "2026-11-05T12:00:00Z"
WINDOW = f"from={FROM}&to={TO}"
TOKEN = "drill-test-token-0123456789"
AUTH = {TOKEN_HEADER: TOKEN}


def epoch_ms(iso: str) -> float:
    when = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    when = when if when.tzinfo else when.replace(tzinfo=timezone.utc)
    return when.timestamp() * 1000


def iso(ms: float) -> str:
    when = datetime.fromtimestamp(ms / 1000, timezone.utc)
    return when.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def values(doc: dict, field: str) -> list:
    value = doc.get(field)
    if value is None:
        return []
    return [v for v in value if v is not None] if isinstance(value, list) else [value]


def _equal(value, wanted, case_insensitive=False) -> bool:
    if isinstance(wanted, str) and "/" in wanted:
        try:
            return ipaddress.ip_address(value) in ipaddress.ip_network(wanted, False)
        except ValueError:
            return False
    if case_insensitive and isinstance(value, str) and isinstance(wanted, str):
        return value.lower() == wanted.lower()
    return value == wanted


def _listed(clauses) -> list:
    return clauses if isinstance(clauses, list) else [clauses]


def matches(doc: dict, query: dict) -> bool:
    ((kind, body),) = query.items()
    if kind == "match_all":
        return True
    if kind == "bool":
        required = _listed(body.get("filter", [])) + _listed(body.get("must", []))
        should = _listed(body.get("should", []))
        least = body.get("minimum_should_match", 0 if required else 1) if should else 0
        return (
            all(matches(doc, c) for c in required)
            and sum(matches(doc, c) for c in should) >= least
            and not any(matches(doc, c) for c in _listed(body.get("must_not", [])))
        )
    if kind == "term":
        ((field, spec),) = body.items()
        wanted, ci = (
            (spec["value"], spec.get("case_insensitive", False))
            if isinstance(spec, dict)
            else (spec, False)
        )
        return any(_equal(v, wanted, ci) for v in values(doc, field))
    if kind == "terms":
        ((field, wanted),) = body.items()
        return any(_equal(v, w) for v in values(doc, field) for w in wanted)
    if kind == "range":
        ((field, bounds),) = body.items()
        checks = {
            "gte": lambda a, b: a >= b,
            "gt": lambda a, b: a > b,
            "lte": lambda a, b: a <= b,
            "lt": lambda a, b: a < b,
        }
        return any(
            all(
                checks[op](epoch_ms(v), epoch_ms(b))
                for op, b in bounds.items()
                if op in checks
            )
            for v in values(doc, field)
        )
    if kind == "exists":
        return bool(values(doc, body["field"]))
    if kind == "prefix":
        ((field, start),) = body.items()
        return any(str(v).startswith(start) for v in values(doc, field))
    if kind == "wildcard":  # on a keyword field: case-sensitive, * and ?
        ((field, pattern),) = body.items()
        return any(fnmatch.fnmatchcase(str(v), pattern) for v in values(doc, field))
    raise NotImplementedError(kind)


def _order(key: tuple) -> tuple:
    return tuple((0,) if v is None else (1, v) for v in key)


def _composite(docs: list, body: dict, sub: dict) -> dict:
    names = [next(iter(s)) for s in body["sources"]]
    groups: dict[tuple, list] = {}
    for doc in docs:
        per_source = []
        for source in body["sources"]:
            spec = next(iter(source.values()))["terms"]
            found = list(dict.fromkeys(values(doc, spec["field"])))
            per_source.append(found or ([None] if spec.get("missing_bucket") else []))
        for key in itertools.product(*per_source):
            groups.setdefault(key, []).append(doc)
    keys = sorted(groups, key=_order)
    if "after" in body:
        after = _order(tuple(body["after"][n] for n in names))
        keys = [k for k in keys if _order(k) > after]
    buckets = [
        {
            "key": dict(zip(names, k)),
            "doc_count": len(groups[k]),
            **aggregate(groups[k], sub),
        }
        for k in keys[: body["size"]]
    ]
    return {
        "buckets": buckets,
        **({"after_key": buckets[-1]["key"]} if buckets else {}),
    }


def _metric(docs: list, kind: str, field: str) -> dict:
    found = [v for d in docs for v in values(d, field)]
    if field == "@timestamp":
        found = [epoch_ms(v) for v in found]
    if kind == "sum":
        return {"value": float(sum(found))}
    if kind == "value_count":
        return {"value": len(found)}
    value = (min if kind == "min" else max)(found) if found else None
    if field == "@timestamp" and value is not None:
        return {"value": value, "value_as_string": iso(value)}
    return {"value": value}


def _one(docs: list, spec: dict) -> dict:
    sub = spec.get("aggs", {})
    ((kind, body),) = ((k, v) for k, v in spec.items() if k != "aggs")
    if kind == "filter":
        hit = [d for d in docs if matches(d, body)]
        return {"doc_count": len(hit), **aggregate(hit, sub)}
    if kind in ("sum", "min", "max", "value_count"):
        return _metric(docs, kind, body["field"])
    if kind == "composite":
        return _composite(docs, body, sub)
    if kind == "terms":  # count desc, then key; cut at size like OpenSearch
        counts: dict = {}
        for d in docs:
            for v in dict.fromkeys(values(d, body["field"])):
                counts[v] = counts.get(v, 0) + 1
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        size = body.get("size", 10)
        return {
            "buckets": [{"key": k, "doc_count": n} for k, n in ranked[:size]],
            "sum_other_doc_count": sum(n for _, n in ranked[size:]),
        }
    if kind == "date_range":
        buckets = []
        for r in body["ranges"]:
            lo, hi = epoch_ms(r["from"]), epoch_ms(r["to"])
            hit = [
                d
                for d in docs
                if any(lo <= epoch_ms(v) < hi for v in values(d, "@timestamp"))
            ]
            buckets.append(
                {"from": lo, "to": hi, "doc_count": len(hit), **aggregate(hit, sub)}
            )
        return {"buckets": buckets}
    raise NotImplementedError(kind)


def aggregate(docs: list, aggs: dict) -> dict:
    return {name: _one(docs, spec) for name, spec in aggs.items()}


# OLD CODE START — NET-178: one index, every requested field mapped (f.keyword included)
# class _Indices:
#     def __init__(self, owner: "DrillOpenSearch") -> None:
#         self._owner = owner
#
#     def get_field_mapping(self, fields, index=None, **params):
#         types = self._owner.mapping_types
#         return {
#             "arkime_sessions3-261105": {
#                 "mappings": {
#                     f: {
#                         "full_name": f,
#                         "mapping": {
#                             f.rsplit(".", 1)[-1]: {"type": types.get(f, "keyword")}
#                         },
#                     }
#                     for f in fields.split(",")
#                 }
#             }
#         }
# OLD CODE END
class _Indices:
    def __init__(self, owner: "DrillOpenSearch") -> None:
        self._owner = owner

    def get_field_mapping(self, fields, index=None, **params):
        return {
            name: {
                "mappings": {
                    f: {"full_name": f, "mapping": {f.rsplit(".", 1)[-1]: spec}}
                    for f in fields.split(",")
                    if (spec := self._owner.spec(f, name)) is not None
                }
            }
            for name in self._owner.index_names
        }


class DrillOpenSearch:
    """Raw documents in, OpenSearch-shaped replies out, each search on a PIT's frozen copy."""

    def __init__(self, docs: list[dict], tamper=None) -> None:
        self.docs = docs
        self.tamper = tamper or (lambda body, reply: reply)
        self.pits: dict[str, list[dict]] = {}
        self.closed: list[str] = []
        self.pit_params: dict = {}
        self.bodies: list[dict] = []
        # OLD CODE START — NET-178: a type per field, one index
        # self.mapping_types: dict[str, str] = {}
        # OLD CODE END
        self.mapping_types: dict = {}
        self.index_names = ["arkime_sessions3-261105"]
        self.indices = _Indices(self)

    def spec(self, field: str, index: str) -> dict | None:
        """{"type", "ignore_above"?} as `index` maps `field`, or None if it doesn't."""
        found = self.mapping_types.get(
            field, None if field.endswith(".keyword") else "keyword"
        )
        if isinstance(found, dict) and "type" not in found:  # per index
            found = found.get(index)
        return {"type": found} if isinstance(found, str) else found

    def _indexed(self, doc: dict) -> dict:
        """`doc` as the first index holds it, for every field `mapping_types` sets."""
        seen = dict(doc)
        for field in self.mapping_types:
            spec = self.spec(field, self.index_names[0])
            if spec is None:
                seen.pop(field, None)
                continue
            limit = spec.get("ignore_above")
            seen[field] = [
                v
                for v in values(doc, field.removesuffix(".keyword"))
                if limit is None or not isinstance(v, str) or len(v) <= limit
            ]
        return seen

    def create_pit(self, index, **params):
        self.pit_params = {"index": index, **params}
        pit = f"pit-{len(self.pits) + len(self.closed)}"
        self.pits[pit] = copy.deepcopy(self.docs)
        return {"pit_id": pit, "_shards": {"total": 1, "failed": 0}}

    def delete_pit(self, body, **params):
        for pit in body["pit_id"]:
            self.pits.pop(pit, None)
            self.closed.append(pit)

    def search(self, body, request_timeout=None):
        assert body["pit"]["id"] in self.pits, "every search runs on the open snapshot"
        self.bodies.append(body)
        # OLD CODE START — NET-178: documents as given, whatever the mapping
        # docs = [d for d in self.pits[body["pit"]["id"]] if matches(d, body["query"])]
        # OLD CODE END
        pit = self.pits[body["pit"]["id"]]
        docs = [d for d in map(self._indexed, pit) if matches(d, body["query"])]
        exact = body.get("track_total_hits") is True or len(docs) <= 10_000
        reply = {
            "pit_id": body["pit"]["id"],
            "timed_out": False,
            "_shards": {"total": 1, "failed": 0},
            "hits": {
                "total": {
                    "value": len(docs) if exact else 10_000,
                    "relation": "eq" if exact else "gte",
                },
                "hits": [],
            },
        }
        if "aggs" in body:
            reply["aggregations"] = aggregate(docs, body["aggs"])
        return self.tamper(body, reply)


def make_app(client, *registers, lan_filter=None, excluded_ips=None) -> web.Application:
    """An app with the real token check and the given `register_*_routes(app, client)`."""
    app = web.Application(middlewares=[make_auth_middleware(TOKEN)])
    if lan_filter is not None:
        app["lan_filter"] = lan_filter
    app["excluded_ips"] = excluded_ips or []
    for register in registers:
        register(app, client)
    return app


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


def conn(src, dst, t="2026-11-05T10:00:00.000Z", **fields) -> dict:
    """A Zeek conn record; source.bytes / destination.bytes only when given."""
    return {
        "@timestamp": t,
        "event.provider": "zeek",
        "event.dataset": "conn",
        "source.ip": src,
        "destination.ip": dst,
        **{k.replace("__", "."): v for k, v in fields.items()},
    }


def dns(
    query, src="192.168.1.20", dst="192.168.1.1", t="2026-11-05T10:00:00.000Z", **fields
):
    return {
        "@timestamp": t,
        "event.provider": "zeek",
        "event.dataset": "dns",
        "zeek.dns.query": query,
        "source.ip": src,
        "destination.ip": dst,
        "destination.port": 53,
        **{k.replace("__", "."): v for k, v in fields.items()},
    }


def ssl_session(
    sni,
    server="93.184.216.34",
    client="192.168.1.20",
    status="ok",
    t="2026-11-05T10:00:00.000Z",
) -> dict:
    return {
        "@timestamp": t,
        "event.provider": "zeek",
        "event.dataset": "ssl",
        "zeek.ssl.server_name": sni,
        "zeek.ssl.validation_status": status,
        "source.ip": client,
        "destination.ip": server,
    }


def alert(src, dst, rule="ET POLICY something", t="2026-11-05T10:00:00.000Z", **fields):
    return {
        "@timestamp": t,
        "event.provider": "suricata",
        "event.dataset": "alert",
        "rule.name": rule,
        "source.ip": src,
        "destination.ip": dst,
        **{k.replace("__", "."): v for k, v in fields.items()},
    }
