"""GET /api/domains/{name} — who looked a name up, what it resolved to, its TLS (NET-160).

The name is canonical (one trailing dot stripped, lower case) and every filter matches it
with or without the dot in any case (services/hostnames.py). The DNS figures use the DNS
page's own rules (DNSAnalytics._bool_clause), so "Lookups" and "Devices" mean the same there
and here. Alerts are a narrow figure: those tagged with this name in one of _HOST_FIELDS,
next to how many alerts in the window carry any of those fields at all. A host field that
can't be matched to a whole name (mapped as text) makes the tagged count a lower bound
that says so, instead of failing the page (NET-178).
"""

import logging
from collections import Counter
from datetime import timedelta
from typing import Any, Callable

from aiohttp import web

from api.alerts import (
    _SURICATA_ALERT_FILTERS,
    SURICATA_NOISE_EXCLUSION,
    _time_range_filter,
)
from api.drilldown_runner import (
    LAST_SEEN,
    LIST_CAP,
    chart_interval,
    chart_slots,
    install,
    ip_param,
    iso_ms,
    json_error,
    lan_check,
    run_drilldown,
    timeline,
    zeek,
)
from api.time_range import parse_time_range
from services.dns_analytics import DNSAnalytics
from services.hostnames import (
    canonical_name,
    keyword_paths,
    name_match,
    require_keyword,
)
from storage.snapshot_search import (
    NETWORK_INDEX,
    Budget,
    QueryFailed,
    SnapshotSearch,
    doc_count,
    metric,
    total_hits,
)

logger = logging.getLogger("nettap.api.domains")

_DEFAULT_RANGE = timedelta(hours=24)
_QUERY = "zeek.dns.query"
_SNI = "zeek.ssl.server_name"
_HTTP_HOST = "zeek.http.host"
# Where a Suricata alert can carry the host name it was about
_HOST_FIELDS = (
    "related.hosts",
    "dns.question.name",
    "tls.client.server_name",
    "url.domain",
)


# OLD CODE START — NET-160 review: the shared LAST_SEEN and zeek() in api/drilldown_runner.py
# _LAST = {"last": {"max": {"field": "@timestamp"}}}
#
#
# def _zeek(dataset: str) -> list[dict]:
#     return [
#         {"term": {"event.provider": "zeek"}},
#         {"term": {"event.dataset": dataset}},
#     ]
# OLD CODE END
# OLD CODE START — NET-160 review: lists ran to 100,000 rows; the shared LAST_SEEN
# def _by_ip(
#     snap: SnapshotSearch,
#     query: dict,
#     field: str,
#     count_key: str,
#     what: str,
#     is_lan: Callable[[str], bool],
#     with_last: bool = False,
# ) -> tuple[list[dict], bool]:
#     """Every value of an IP field with its record count, most first; False if capped."""
#     buckets, complete = snap.groups(
#         query, [{"ip": {"terms": {"field": field}}}], _LAST if with_last else None, what
#     )
#     rows = [
#         {
#             "ip": b["key"]["ip"],
#             "lan": is_lan(b["key"]["ip"]),
#             count_key: doc_count(b, what),
#             **({"last_seen": iso_ms(metric(b, "last", what))} if with_last else {}),
#         }
#         for b in buckets
#     ]
#     if not complete:
#         logger.info("Domain drill-down: the %s list stopped at its cap", what)
#     return sorted(rows, key=lambda r: (-r[count_key], r["ip"])), complete
# OLD CODE END
def _by_ip(
    snap: SnapshotSearch,
    query: dict,
    field: str,
    count_key: str,
    what: str,
    is_lan: Callable[[str], bool],
    with_last: bool = False,
) -> tuple[list[dict], bool]:
    """Every value of an IP field with its record count, most first; False if capped."""
    buckets, complete = snap.groups(
        query,
        [{"ip": {"terms": {"field": field}}}],
        LAST_SEEN if with_last else None,
        what,
        max_buckets=LIST_CAP,
    )
    rows = [
        {
            "ip": b["key"]["ip"],
            "lan": is_lan(b["key"]["ip"]),
            count_key: doc_count(b, what),
            **({"last_seen": iso_ms(metric(b, "last", what))} if with_last else {}),
        }
        for b in buckets
    ]
    if not complete:
        logger.info("Domain drill-down: the %s list stopped at its cap", what)
    return sorted(rows, key=lambda r: (-r[count_key], r["ip"])), complete


def _answer(value: Any, lookups: int, is_lan: Callable[[str], bool]) -> dict:
    """An answer as an address, a host name (e.g. a CNAME) or other text (TXT and the like)."""
    ip = ip_param(value)
    if ip:
        return {"value": ip, "kind": "ip", "lan": is_lan(ip), "lookups": lookups}
    host = canonical_name(value)
    if host:
        return {"value": host, "kind": "name", "lan": None, "lookups": lookups}
    return {"value": str(value), "kind": "other", "lan": None, "lookups": lookups}


def _merged(answers: list[dict]) -> list[dict]:
    """One row per answer after normalising (Edge.Example.NET and edge.example.net, or
    2001:DB8::1 and 2001:db8::1, are one answer), lookups summed, most first.

    A response holding two spellings of one answer would count twice; Zeek writes each
    answer once, so that needs a server sending the same record in two spellings.
    """
    lookups: Counter = Counter()
    first: dict[tuple, dict] = {}
    for a in answers:
        key = (a["kind"], a["value"])
        first.setdefault(key, a)
        lookups[key] += a["lookups"]
    rows = [{**first[key], "lookups": n} for key, n in lookups.items()]
    return sorted(rows, key=lambda a: -a["lookups"])


def _every_value(snap: SnapshotSearch, query: dict, field: str, what: str) -> list:
    """(value, count) of a field with a few values (response codes, validation results);
    QueryFailed if it ever holds more than a list can carry, never a cut list."""
    buckets, complete = snap.groups(
        query,
        [{"value": {"terms": {"field": field, "missing_bucket": True}}}],
        None,
        what,
        max_buckets=LIST_CAP,
    )
    if not complete:
        raise QueryFailed(f"{what}: more values than one page can list")
    return [(b["key"]["value"], doc_count(b, what)) for b in buckets]


def _dns(
    snap: SnapshotSearch,
    query: dict,
    slots: dict,
    is_lan: Callable[[str], bool],
) -> dict:
    reply = snap.search(
        {
            "size": 0,
            "track_total_hits": True,
            "query": query,
            "aggs": {"timeline": slots},
        },
        "domain lookups",
        ("timeline",),
    )
    askers, askers_complete = _by_ip(
        snap, query, "source.ip", "lookups", "domain askers", is_lan, with_last=True
    )
    # OLD CODE START — NET-160 review: raw answers were grouped before normalising, so two
    # spellings of one answer became two rows; the response codes' cap went unchecked
    # found, answers_complete = snap.groups(
    #     query,
    #     [{"value": {"terms": {"field": "zeek.dns.answers"}}}],
    #     None,
    #     "domain answers",
    # )
    # answers = sorted(
    #     (
    #         _answer(b["key"]["value"], doc_count(b, "domain answers"), is_lan)
    #         for b in found
    #     ),
    #     key=lambda a: -a["lookups"],
    # )
    # if not answers_complete:
    #     logger.info("Domain drill-down: the answers list stopped at its cap")
    # # A handful of response codes exist, so this list never nears the cap
    # codes, _ = snap.groups(
    #     query,
    #     [
    #         {
    #             "rcode": {
    #                 "terms": {"field": "zeek.dns.rcode_name", "missing_bucket": True}
    #             }
    #         }
    #     ],
    #     None,
    #     "domain response codes",
    # )
    # OLD CODE END
    found, answers_complete = snap.groups(
        query,
        [{"value": {"terms": {"field": "zeek.dns.answers"}}}],
        None,
        "domain answers",
        max_buckets=LIST_CAP,
    )
    answers = _merged(
        [
            _answer(b["key"]["value"], doc_count(b, "domain answers"), is_lan)
            for b in found
        ]
    )
    if not answers_complete:
        logger.info("Domain drill-down: the answers list stopped at its cap")
    codes = _every_value(snap, query, "zeek.dns.rcode_name", "domain response codes")
    return {
        "lookups": total_hits(reply, "domain lookups"),
        "askers": askers,
        "askers_complete": askers_complete,
        "answers": answers,
        "answers_complete": answers_complete,
        "addresses": len({a["value"] for a in answers if a["kind"] == "ip"})
        if answers_complete
        else None,
        # OLD CODE START — NET-160 review: read from _every_value's pairs now
        # "rcodes": sorted(
        #     (
        #         {"rcode": b["key"]["rcode"], "lookups": doc_count(b, "rcodes")}
        #         for b in codes
        #     ),
        #     key=lambda r: -r["lookups"],
        # ),
        # OLD CODE END
        "rcodes": sorted(
            ({"rcode": code, "lookups": n} for code, n in codes),
            key=lambda r: -r["lookups"],
        ),
        "timeline": timeline(reply),
    }


def _tls(snap: SnapshotSearch, query: dict, is_lan: Callable[[str], bool]) -> dict:
    servers, servers_complete = _by_ip(
        snap, query, "destination.ip", "sessions", "domain TLS servers", is_lan
    )
    clients, clients_complete = _by_ip(
        snap, query, "source.ip", "sessions", "domain TLS clients", is_lan
    )
    # OLD CODE START — NET-160 review: the statuses' cap went unchecked
    # # Validation results are a short list of OpenSSL outcomes, never near the cap
    # found, _ = snap.groups(
    #     query,
    #     [
    #         {
    #             "status": {
    #                 "terms": {
    #                     "field": "zeek.ssl.validation_status",
    #                     "missing_bucket": True,
    #                 }
    #             }
    #         }
    #     ],
    #     None,
    #     "domain TLS statuses",
    # )
    # statuses: Counter = Counter()
    # for b in found:
    #     statuses[b["key"]["status"] or "unchecked"] += doc_count(b, "TLS statuses")
    # OLD CODE END
    statuses: Counter = Counter()
    for status, n in _every_value(
        snap, query, "zeek.ssl.validation_status", "domain TLS statuses"
    ):
        statuses[status or "unchecked"] += n
    return {
        "sessions": snap.count(query, "domain TLS sessions"),
        "servers": servers,
        "servers_complete": servers_complete,
        "clients": clients,
        "clients_complete": clients_complete,
        "statuses": dict(statuses),
    }


# OLD CODE START — NET-178: matched every host field by term, so one mapped as text (as
# tls.client.server_name is on the G11) failed the whole page in require_keyword
# def _alerts(snap: SnapshotSearch, name: str, window: dict) -> dict:
#     """Alerts tagged with the name, and how many in the window carry a host field at all."""
#     what = "domain alerts"
#
#     def any_of(clauses: list[dict]) -> dict:
#         return {"filter": {"bool": {"should": clauses, "minimum_should_match": 1}}}
#
#     reply = snap.search(
#         {
#             "size": 0,
#             "track_total_hits": True,
#             "query": {
#                 "bool": {
#                     "filter": [window, *_SURICATA_ALERT_FILTERS],
#                     "must_not": SURICATA_NOISE_EXCLUSION,
#                 }
#             },
#             "aggs": {
#                 "with_host": any_of([{"exists": {"field": f}} for f in _HOST_FIELDS]),
#                 "tagged": any_of([name_match(f, name) for f in _HOST_FIELDS]),
#             },
#         },
#         what,
#         ("with_host", "tagged"),
#     )
#     aggs = reply["aggregations"]
#     with_host = doc_count(aggs["with_host"], what)
#     return {
#         # No alert carries a host field: the count would be a 0 nothing backs
#         "tagged": doc_count(aggs["tagged"], what) if with_host else None,
#         "alerts_in_window": total_hits(reply, what),
#         "with_host_field": with_host,
#     }
# OLD CODE END
def _alerts(
    snap: SnapshotSearch,
    name: str,
    window: dict,
    matched: list[str],
    unmatched: list[str],
) -> dict:
    """Alerts tagged with the name, and how many in the window carry a host field at all.

    `matched` are the paths keyword_paths found for _HOST_FIELDS, `unmatched` the mapped
    fields it can't match. With any unmatched, the tagged count is a lower bound: exact for
    every alert it counts, missing those that name the host only in an unmatched field.
    """
    what = "domain alerts"

    def any_of(clauses: list[dict]) -> dict:
        return {"filter": {"bool": {"should": clauses, "minimum_should_match": 1}}}

    # A .keyword path can hold a value its parent's ignore_above drops, so it carries too
    carriers = list(dict.fromkeys([*_HOST_FIELDS, *matched]))
    aggs = {"with_host": any_of([{"exists": {"field": f}} for f in carriers])}
    if matched:
        aggs["tagged"] = any_of([name_match(f, name) for f in matched])
    reply = snap.search(
        {
            "size": 0,
            "track_total_hits": True,
            "query": {
                "bool": {
                    "filter": [window, *_SURICATA_ALERT_FILTERS],
                    "must_not": SURICATA_NOISE_EXCLUSION,
                }
            },
            "aggs": aggs,
        },
        what,
        tuple(aggs),
    )
    found = reply["aggregations"]
    with_host = doc_count(found["with_host"], what)
    return {
        # No alert carries a host field, or no field can be matched: a 0 nothing backs
        "tagged": doc_count(found["tagged"], what) if with_host and matched else None,
        "tagged_partial": bool(with_host and unmatched),
        "matched_fields": matched,
        "unmatched_fields": unmatched,
        "alerts_in_window": total_hits(reply, what),
        "with_host_field": with_host,
    }


def domain_figures(
    client: Any,
    name: str,
    from_ts: str,
    to_ts: str,
    excluded: list[str],
    slots: dict,
    is_lan: Callable[[str], bool],
    budget: Budget,
) -> dict:
    """Every figure the domain page shows, over one snapshot."""
    # OLD CODE START — NET-178: an alert host field mapped as text failed the whole page
    # require_keyword(client, [_QUERY, _SNI, _HTTP_HOST, *_HOST_FIELDS], budget)
    # OLD CODE END
    require_keyword(client, [_QUERY, _SNI, _HTTP_HOST], budget)
    matched, unmatched = keyword_paths(client, list(_HOST_FIELDS), budget)
    # OLD CODE START — NET-160 review: the shared alerts filter and zeek()
    # window = window_filter(from_ts, to_ts)
    # dns_clause = DNSAnalytics(client)._bool_clause(
    #     from_ts, to_ts, excluded, [name_match(_QUERY, name)]
    # )
    # tls_query = {"bool": {"filter": [window, *_zeek("ssl"), name_match(_SNI, name)]}}
    # http_query = {
    #     "bool": {"filter": [window, *_zeek("http"), name_match(_HTTP_HOST, name)]}
    # }
    # OLD CODE END
    window = _time_range_filter(from_ts, to_ts)
    dns_clause = DNSAnalytics(client)._bool_clause(
        from_ts, to_ts, excluded, [name_match(_QUERY, name)]
    )
    tls_query = {"bool": {"filter": [window, *zeek("ssl"), name_match(_SNI, name)]}}
    http_query = {
        "bool": {"filter": [window, *zeek("http"), name_match(_HTTP_HOST, name)]}
    }
    with SnapshotSearch(client, NETWORK_INDEX, budget) as snap:
        dns = _dns(snap, {"bool": dns_clause}, slots, is_lan)
        tls = _tls(snap, tls_query, is_lan)
        http = {"requests": snap.count(http_query, "domain HTTP requests")}
        # OLD CODE START — NET-178: every host field was matched
        # alerts = _alerts(snap, name, window)
        # OLD CODE END
        alerts = _alerts(snap, name, window, matched, unmatched)
    return {
        "name": name,
        "from": from_ts,
        "to": to_ts,
        "dns": dns,
        "tls": tls,
        "http": http,
        "alerts": alerts,
    }


async def handle_domain(request: web.Request) -> web.Response:
    """GET /api/domains/{name}?from=&to=&interval= — the domain page's figures."""
    name = canonical_name(request.match_info["name"])
    if name is None:
        return json_error("That is not a host name.", 400)
    from_ts, to_ts = parse_time_range(request, _DEFAULT_RANGE)
    # OLD CODE: slots = chart_slots(from_ts, to_ts) (NET-249: the chart's bucket can be asked for)
    interval = chart_interval(request, from_ts, to_ts)
    slots = chart_slots(from_ts, to_ts, interval)
    if slots is None:
        return json_error("This time range is too long; choose a shorter one.", 400)
    client, is_lan = request.app["drill_client"], lan_check(request.app)
    excluded = list(request.app.get("excluded_ips", []))
    return await run_drilldown(
        request,
        # OLD CODE: lambda budget: domain_figures(...) (NET-249: + the bucket the slots used)
        lambda budget: {
            **domain_figures(
                client, name, from_ts, to_ts, excluded, slots, is_lan, budget
            ),
            "interval": interval,
        },
        f"domain {name}",
    )


def register_domain_routes(app: web.Application, client: Any) -> None:
    install(app, client)
    app.router.add_get("/api/domains/{name}", handle_domain)
    logger.info("Domain API routes registered (1 endpoint)")
