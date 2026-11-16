"""
NetTap Security posture detail (the posture category pages).

GET /api/posture/{category}?from=&to= says what drives the Encryption, DNS security and Patch
currency scores, by device. The base query is /api/traffic/protocols' own, so every filter total
here equals the figure the score uses. The page decides its advice from the fixed filters; the
device lists are for display only (the top 10, with how many connections they leave out).

GET /api/posture/alert-response?from=&to= is the Alert response score's input (NET-308): the
high-severity rules among the counted alerts, and which of them an investigation open during the
window links an alert of.
"""

import ipaddress
import logging
from typing import Any, Callable

from aiohttp import web
from opensearchpy import OpenSearchException

from api.alerts import _every_key, _primary_severity
from api.error_replies import incomplete, public_json
from api.offload import in_thread, run_blocking
from api.traffic import (
    LEGACY_PROTOCOLS,
    NETWORK_INDEX,
    PRIVATE_LOCAL,
    PRIVATE_LOCAL_SCOPE,
    _PAYLOAD_FIELDS,
    _ZEEK_CONN_FILTERS,
    _get_client,
    _parse_time_range,
    _time_range_filter,
)
from services.dns_analytics import LOCAL_NAME_SERVICE_PORTS
from services.excluded_ips import (
    PAYLOAD_BOTH,
    RFC1918_SOURCE_FILTER,
    build_excluded_ips_filter,
    valid_excluded_ips,
)
from services.iot_monitor import (
    ENCRYPTED_CONN_FILTER,
    ENCRYPTED_PORTS,
    ENCRYPTED_PROTOCOLS,
    LOCAL_CHATTER_EXCLUSION,
    NO_PAYLOAD_PROTOCOLS,
)
from services.investigation_store import InvestigationStore, clean_alert_rules
from storage.exact_terms import PartialResultsError
from storage.snapshot_search import QueryFailed, checked

logger = logging.getLogger("nettap.api.posture")

DEVICE_ROWS = 10  # devices listed per check
TOP = 3  # services, ports, destinations or resolvers per device
# OLD CODE START — NET-308: moved to api/traffic.py, whose protocol figures (the scores) need them
# # The Patch currency score's legacy names; keep in step with web/src/lib/posture/score.ts
# LEGACY_PROTOCOLS = ["http", "ftp", "telnet", "pop3", "imap"]
#
# # Address scope. "Private or local-scope" is what the address says, not proof the traffic stayed
# # in this network (a routed VPN address is private too). dns_analytics' LOCAL_DESTINATIONS is left
# # alone: other features read it, and it has no IPv6 ULA.
# PRIVATE_LOCAL_SCOPE = [
#     "10.0.0.0/8",
#     "172.16.0.0/12",
#     "192.168.0.0/16",
#     "127.0.0.0/8",
#     "169.254.0.0/16",
#     "224.0.0.0/4",
#     "255.255.255.255",
#     "fc00::/7",
#     "fe80::/10",
#     "ff00::/8",
#     "::1/128",
# ]
# OLD CODE END
# Shared address space: an ISP's carrier-grade NAT or a VPN, so neither side can be named
UNKNOWN_SCOPE = ["100.64.0.0/10"]
_PRIVATE_NETS = [ipaddress.ip_network(n) for n in PRIVATE_LOCAL_SCOPE]
_UNKNOWN_NETS = [ipaddress.ip_network(n) for n in UNKNOWN_SCOPE]

# OLD CODE: PRIVATE_LOCAL: dict = {"terms": {"destination.ip": PRIVATE_LOCAL_SCOPE}} (NET-308: in api/traffic.py)
UNKNOWN: dict = {
    "bool": {
        "should": [
            {"terms": {"destination.ip": UNKNOWN_SCOPE}},
            {"bool": {"must_not": [{"exists": {"field": "destination.ip"}}]}},
        ],
        "minimum_should_match": 1,
    }
}
PUBLIC: dict = {"bool": {"must_not": [PRIVATE_LOCAL, UNKNOWN]}}

# OLD CODE START — NET-308: one definition in services/excluded_ips.py (imported above)
# # NET-219's rule: both payload counters above 0. Anything else is "other" (one way, none, or not measured)
# PAYLOAD_BOTH: dict = {
#     "bool": {"filter": [{"range": {f: {"gt": 0}}} for f in _PAYLOAD_FIELDS]}
# }
# OLD CODE END
# /api/traffic/protocols' encryption and dns_plain filters (a test holds them equal)
ELIGIBLE: dict = {
    "bool": {
        "must_not": [
            *LOCAL_CHATTER_EXCLUSION,
            {"terms": {"network.protocol": NO_PAYLOAD_PROTOCOLS}},
        ]
    }
}
UNENCRYPTED: dict = {"bool": {"must_not": [ENCRYPTED_CONN_FILTER]}}
DNS_PLAIN: dict = {
    "bool": {
        "filter": [{"term": {"network.protocol": "dns"}}],
        "must_not": [{"terms": {"destination.port": LOCAL_NAME_SERVICE_PORTS}}],
    }
}
DOT: dict = {"term": {"destination.port": 853}}

# Fixed filters the page's advice reads, so a quiet Telnet service can't hide behind busier ones
_RISKY: dict[str, tuple[str, int | None]] = {
    "telnet": ("telnet", 23),
    "ftp": ("ftp", 21),
    "http": ("http", None),
}

Search = Callable[[dict, str], dict]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def scope(ip: Any) -> str:
    """'private_local', 'unknown' or 'public', by the same lists as the scope filters."""
    try:
        addr = ipaddress.ip_address(str(ip))
    except ValueError:
        return "unknown"
    if any(addr in net for net in _PRIVATE_NETS):
        return "private_local"
    if any(addr in net for net in _UNKNOWN_NETS):
        return "unknown"
    return "public"


def _risky_filter(name: str) -> dict:
    protocol, port = _RISKY[name]
    if port is None:
        return {"term": {"network.protocol": protocol}}
    return {
        "bool": {
            "should": [
                {"term": {"network.protocol": protocol}},
                {"term": {"destination.port": port}},
            ],
            "minimum_should_match": 1,
        }
    }


def _q_value(value: Any) -> str:
    if isinstance(value, int):
        return str(value)
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _q_terms(field: str, values: Any) -> str:
    values = values if isinstance(values, list) else [values]
    return f"{field}:({' OR '.join(_q_value(v) for v in values)})"


def _q_not(clause: dict) -> str:
    """NOT of one term/terms clause; anything else is a programming error the tests catch."""
    ((kind, body),) = clause.items()
    if kind not in ("term", "terms"):
        raise ValueError(f"can't write {kind} as a Log Explorer query")
    ((field, values),) = body.items()
    return f"NOT {_q_terms(field, values)}"


def logs_query(name: str) -> str:
    """Log Explorer's query for one risky bucket: its clause within the eligible, unencrypted set,
    written from the same constants as the filters so the two can't drift."""
    protocol, port = _RISKY[name]
    risky = _q_terms("network.protocol", protocol)
    if port is not None:
        risky = f"({risky} OR {_q_terms('destination.port', port)})"
    exclusions = [
        *LOCAL_CHATTER_EXCLUSION,
        {"terms": {"network.protocol": NO_PAYLOAD_PROTOCOLS}},
        {"terms": {"destination.port": ENCRYPTED_PORTS}},
        {"terms": {"network.protocol": ENCRYPTED_PROTOCOLS}},
    ]
    # OLD CODE: return " AND ".join([risky, *(_q_not(c) for c in exclusions)]) (NET-308)
    # NET-308: the scored set is connections with data both ways (PAYLOAD_BOTH)
    payload = [f"{f}:>0" for f in _PAYLOAD_FIELDS]
    return " AND ".join([risky, *(_q_not(c) for c in exclusions), *payload])


def _terms(field: str, size: int, missing: str | None = None) -> dict:
    body: dict = {"field": field, "size": size}
    if missing is not None:
        body["missing"] = missing
    return {"terms": body}


def _pairs(agg: dict, key: str) -> list[dict]:
    return [{key: b["key"], "count": b["doc_count"]} for b in agg.get("buckets", [])]


def _org(bucket: dict) -> str | None:
    orgs = bucket.get("org", {}).get("buckets", [])
    return orgs[0]["key"] if orgs else None


def _devices(app: web.Application, aggs: dict | None = None) -> dict:
    """LAN sources only, the busiest DEVICE_ROWS of them."""
    rows: dict = _terms("source.ip", DEVICE_ROWS)
    if aggs:
        rows["aggs"] = aggs
    return {
        "filter": app.get("lan_filter", RFC1918_SOURCE_FILTER),
        "aggs": {"rows": rows},
    }


def _device_list(agg: dict, row: Callable[[dict], dict]) -> dict:
    """lan: connections from LAN devices; other: those from devices not in rows."""
    rows = agg.get("rows", {})
    return {
        "lan": agg.get("doc_count", 0),
        "other": rows.get("sum_other_doc_count", 0),
        "rows": [row(b) for b in rows.get("buckets", [])],
    }


def _count(agg: dict, name: str) -> int:
    return agg.get(name, {}).get("doc_count", 0)


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------


def _encryption(app: web.Application, search: Search) -> dict:
    # OLD CODE START — NET-308: every eligible connection was scored, one-way attempts included
    # aggs = {
    #     "eligible": {
    #         "filter": ELIGIBLE,
    #         "aggs": {
    #             "encrypted": {"filter": ENCRYPTED_CONN_FILTER},
    #             "unencrypted": {
    #                 "filter": UNENCRYPTED,
    #                 "aggs": {
    #                     "payload_both": {"filter": PAYLOAD_BOTH},
    #                     "private_local": {"filter": PRIVATE_LOCAL},
    #                     "risky": {
    #                         "filters": {
    #                             "filters": {n: _risky_filter(n) for n in _RISKY}
    #                         }
    #                     },
    #                     "services": _terms("network.protocol", 10, "unknown"),
    #                     "devices": _devices(
    #                         app,
    #                         {
    #                             "payload_both": {"filter": PAYLOAD_BOTH},
    #                             "private_local": {"filter": PRIVATE_LOCAL},
    #                             "services": _terms("network.protocol", TOP, "unknown"),
    #                             "ports": _terms("destination.port", TOP),
    #                         },
    #                     ),
    #                 },
    #             },
    #         },
    #     }
    # }
    # OLD CODE END
    # NET-308: only connections with data both ways are scored, so every figure here is that set
    aggs = {
        "eligible": {
            "filter": ELIGIBLE,
            "aggs": {
                "both": {
                    "filter": PAYLOAD_BOTH,
                    "aggs": {
                        "encrypted": {"filter": ENCRYPTED_CONN_FILTER},
                        "unencrypted": {
                            "filter": UNENCRYPTED,
                            "aggs": {
                                "private_local": {"filter": PRIVATE_LOCAL},
                                "risky": {
                                    "filters": {
                                        "filters": {n: _risky_filter(n) for n in _RISKY}
                                    }
                                },
                                "services": _terms("network.protocol", 10, "unknown"),
                                "devices": _devices(
                                    app,
                                    {
                                        "private_local": {"filter": PRIVATE_LOCAL},
                                        "services": _terms(
                                            "network.protocol", TOP, "unknown"
                                        ),
                                        "ports": _terms("destination.port", TOP),
                                    },
                                ),
                            },
                        },
                    },
                }
            },
        }
    }
    # OLD CODE: eligible = search(aggs, "posture encryption")["aggregations"]["eligible"] (NET-308)
    eligible = search(aggs, "posture encryption")["aggregations"]["eligible"].get(
        "both", {}
    )
    un = eligible.get("unencrypted", {})
    risky = un.get("risky", {}).get("buckets", {})
    return {
        "eligible": eligible.get("doc_count", 0),
        "encrypted": _count(eligible, "encrypted"),
        "unencrypted": {
            "total": un.get("doc_count", 0),
            # OLD CODE: "payload_both": _count(un, "payload_both"), (NET-308: always the total now)
            "private_local": _count(un, "private_local"),
            "services": _pairs(un.get("services", {}), "name"),
            "services_other": un.get("services", {}).get("sum_other_doc_count", 0),
            "risky": {
                n: {
                    "count": risky.get(n, {}).get("doc_count", 0),
                    "logs_query": logs_query(n),
                }
                for n in _RISKY
            },
        },
        "devices": _device_list(
            un.get("devices", {}),
            lambda b: {
                "ip": b["key"],
                "connections": b["doc_count"],
                # OLD CODE: "payload_both": _count(b, "payload_both"), (NET-308: always the count now)
                "private_local": _count(b, "private_local"),
                "services": _pairs(b.get("services", {}), "name"),
                "ports": _pairs(b.get("ports", {}), "port"),
            },
        ),
    }


def _resolver(bucket: dict) -> dict:
    return {
        "ip": bucket["key"],
        "count": bucket["doc_count"],
        "org": _org(bucket),
        "scope": scope(bucket["key"]),
    }


def _dns(app: web.Application, search: Search) -> dict:
    org = {"org": _terms("destination.as.full", 1)}
    aggs = {
        "plain": {
            "filter": DNS_PLAIN,
            "aggs": {
                "private_local": {"filter": PRIVATE_LOCAL},
                "unknown": {"filter": UNKNOWN},
                "public": {
                    "filter": PUBLIC,
                    "aggs": {
                        "devices": _devices(
                            app,
                            {
                                "resolvers": {
                                    **_terms("destination.ip", TOP),
                                    "aggs": org,
                                }
                            },
                        )
                    },
                },
                "resolvers": {**_terms("destination.ip", 10), "aggs": org},
            },
        },
        "over_tls": {
            "filter": DOT,
            "aggs": {"resolvers": {**_terms("destination.ip", 5), "aggs": org}},
        },
    }
    found = search(aggs, "posture DNS")["aggregations"]
    plain, over_tls = found["plain"], found["over_tls"]
    resolvers = [_resolver(b) for b in plain.get("resolvers", {}).get("buckets", [])]

    # Each private/local-scope resolver's own traffic out, by a filter of its own, so the page
    # never reads "no DoT" from a resolver missing from a top-10 list
    local = [r["ip"] for r in resolvers if r["scope"] == "private_local"]
    upstream: dict = {}
    if local:
        found2 = search(
            {
                "upstream": {
                    "filters": {
                        "filters": {ip: {"term": {"source.ip": ip}} for ip in local}
                    },
                    "aggs": {
                        "plain_public": {
                            "filter": {"bool": {"filter": [DNS_PLAIN, PUBLIC]}}
                        },
                        "dot": {"filter": DOT},
                    },
                }
            },
            "posture DNS resolvers",
        )
        upstream = found2["aggregations"]["upstream"].get("buckets", {})
    for r in resolvers:
        b = upstream.get(r["ip"]) if r["scope"] == "private_local" else None
        r["upstream"] = (
            {"plain_public": _count(b, "plain_public"), "dot": _count(b, "dot")}
            if b is not None
            else None
        )

    public = plain.get("public", {})
    return {
        "plain": plain.get("doc_count", 0),
        "over_tls": over_tls.get("doc_count", 0),
        "plain_scope": {
            "private_local": _count(plain, "private_local"),
            "unknown": _count(plain, "unknown"),
            "public": public.get("doc_count", 0),
        },
        "resolvers": {
            "plain": resolvers,
            "over_tls": [
                _resolver(b) for b in over_tls.get("resolvers", {}).get("buckets", [])
            ],
        },
        "public_devices": _device_list(
            public.get("devices", {}),
            lambda b: {
                "ip": b["key"],
                "count": b["doc_count"],
                "resolvers": [
                    {"ip": r["key"], "count": r["doc_count"], "org": _org(r)}
                    for r in b.get("resolvers", {}).get("buckets", [])
                ],
            },
        ),
    }


def _patch(app: web.Application, search: Search) -> dict:
    aggs = {
        "legacy": {
            "filter": {"terms": {"network.protocol": LEGACY_PROTOCOLS}},
            "aggs": {
                # include: a two-label record (ssl,http) must not add an ssl row; 5 names, size 5
                "services": {
                    "terms": {
                        "field": "network.protocol",
                        "include": LEGACY_PROTOCOLS,
                        "size": len(LEGACY_PROTOCOLS),
                    },
                    "aggs": {
                        "devices": _devices(
                            app,
                            {
                                "ports": _terms("destination.port", TOP),
                                "destinations": _terms("destination.ip", TOP),
                            },
                        )
                    },
                }
            },
        }
    }
    legacy = search(aggs, "posture patch")["aggregations"]["legacy"]
    return {
        "unique_connections": legacy.get("doc_count", 0),
        "protocols": [
            {
                "name": s["key"],
                "count": s["doc_count"],
                "devices": _device_list(
                    s.get("devices", {}),
                    lambda b: {
                        "ip": b["key"],
                        "connections": b["doc_count"],
                        "ports": _pairs(b.get("ports", {}), "port"),
                        "destinations": _pairs(b.get("destinations", {}), "ip"),
                    },
                ),
            }
            for s in legacy.get("services", {}).get("buckets", [])
        ],
    }


_CATEGORIES: dict[str, Callable[[web.Application, Search], dict]] = {
    "encryption": _encryption,
    "dns-security": _dns,
    "patch-currency": _patch,
}


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@in_thread
def handle_posture_detail(request: web.Request) -> web.Response:
    """GET /api/posture/{category}?from=&to= for encryption, dns-security or patch-currency."""
    category = request.match_info.get("category", "")
    build = _CATEGORIES.get(category)
    if build is None:
        return public_json({"error": "Unknown posture category"}, status=404)
    from_ts, to_ts = _parse_time_range(request)
    excluded = valid_excluded_ips(request.app.get("excluded_ips", []))
    client = _get_client(request)
    # /api/traffic/protocols' base query, so the filter totals equal the score's inputs
    base = {
        "bool": {
            "filter": [_time_range_filter(from_ts, to_ts), *_ZEEK_CONN_FILTERS],
            "must_not": build_excluded_ips_filter(excluded),
        }
    }

    def search(aggs: dict, what: str) -> dict:
        body = {"size": 0, "query": base, "aggs": aggs}
        return checked(client.search(index=NETWORK_INDEX, body=body), what, tuple(aggs))

    try:
        detail = build(request.app, search)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in posture %s: %s", category, exc)
        return public_json({"error": "The posture search failed"}, status=502)
    except QueryFailed as exc:
        logger.warning("Posture %s: %s", category, exc)
        return public_json({"error": "The posture search was incomplete"}, status=502)

    return web.json_response(
        {
            "category": category,
            "from": from_ts,
            "to": to_ts,
            "excluded_ips": excluded,
            **detail,
        }
    )


# ---------------------------------------------------------------------------
# Alert response (NET-308)
# ---------------------------------------------------------------------------

RESPONSE_GROUPS = 25  # groups listed; needing and investigated count them all
_HIGH = 1  # Suricata priority 1, NetTap's High (suricataLevel tops out there)


def _coverage(investigations: list) -> tuple[set, dict]:
    """The rules (str, "" or None) the investigations' resolved links cover, and the counts the
    page reports. A record whose alert_ids isn't a list of ids is skipped; a link with no rule
    recorded (made before NET-308) is unresolved and covers nothing."""
    covered: set = set()
    counts = {
        "open_during": len(investigations),
        "linked_alerts": 0,
        "unresolved_links": 0,
        "skipped": 0,
    }
    for inv in investigations:
        ids = inv.alert_ids
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            logger.warning(
                "Investigation %s: alert_ids isn't a list of ids, left out", inv.id
            )
            counts["skipped"] += 1
            continue
        rules = clean_alert_rules(inv.alert_rules)
        counts["linked_alerts"] += len(ids)
        for alert_id in ids:
            if alert_id in rules:
                covered.add(rules[alert_id])
            else:
                counts["unresolved_links"] += 1
    return covered, counts


async def handle_alert_response(request: web.Request) -> web.Response:
    """GET /api/posture/alert-response?from=&to=. Async: the store isn't thread-safe, so it is
    read on the loop; only the alert scan runs on the route pool."""
    from_ts, to_ts = _parse_time_range(request)
    severity = {"severity": {"terms": {"field": "suricata.alert.severity", "size": 3}}}
    try:
        # top-signatures' exact scan of the counted alerts, so the groups equal the Alerts list
        buckets, complete = await run_blocking(
            _every_key,
            _get_client(request),
            from_ts,
            to_ts,
            {"field": "rule.name", "missing_bucket": True},
            severity,
            "posture alert response",
        )
    except PartialResultsError as exc:
        return incomplete("alert", exc)
    except OpenSearchException as exc:
        logger.error("OpenSearch error in posture alert response: %s", exc)
        return public_json({"error": "The alert search failed"}, status=502)
    except QueryFailed as exc:
        logger.warning("Posture alert response: %s", exc)
        return public_json({"error": "The alert search was incomplete"}, status=502)
    if not complete:  # fail closed: a part of the rules can't be graded
        return public_json({"error": "The alert search was incomplete"}, status=502)

    store: InvestigationStore = request.app["investigation_store"]
    covered, counts = _coverage(store.open_during(from_ts, to_ts))
    groups = [
        {"rule": b["key"]["key"], "count": b["doc_count"]}
        for b in buckets
        if _primary_severity(b) == _HIGH
    ]
    for g in groups:
        g["investigated"] = g["rule"] in covered
    # the ones without an investigation first, then the busiest
    groups.sort(
        key=lambda g: (
            g["investigated"],
            -g["count"],
            g["rule"] is None,
            g["rule"] or "",
        )
    )
    return web.json_response(
        {
            "category": "alert-response",
            "from": from_ts,
            "to": to_ts,
            "needing": len(groups),
            "investigated": sum(g["investigated"] for g in groups),
            "groups": groups[:RESPONSE_GROUPS],
            "investigations": counts,
        }
    )


def register_posture_routes(app: web.Application) -> None:
    """Register the posture routes on the given aiohttp application."""
    # before {category}: aiohttp matches in registration order
    app.router.add_get("/api/posture/alert-response", handle_alert_response)
    app.router.add_get("/api/posture/{category}", handle_posture_detail)
    logger.info("Posture API routes registered (2 endpoints)")
